# import the libraries
from appJar import gui
from PIL import Image, ImageTk
import numpy as np
import cv2
import threading
import socket
import json
import time
from discovery import server_init, server_quit, register_user, query_user
from control import *
from video import *



class VideoClient(object):

    connection_loop = None #Hilo que despacha las conexiones entrantes
    command_loop = None #Hilo que atiende a los comandos de llamada entrantes
    nick = None #Nombre de usuario
    listen_control_port = "10000" #Puerto de escucha para control
    boolResetFrame = 1 #Indica si han de resetearse los campos propios de la llamada la siguiente vez que se actualice frame.
    socket_video_send = None #Socket UDP para enviar video
    socket_video_rec = None #Socket UDP para recibir video
    num = 0 #Numero de secuencia del frame actual
    buffer_video = None #Buffer con los frames de video
    buffer_block = [True] #Indicara al buffer si puede sacar frames o no. Solo lo levantaremos cuando este parcialmente lleno.
    currently_playing_file = None #Nombre del fichero que se esta enviando actualmente.

    def __init__(self, window_size):

        # Creamos una variable que contenga el GUI principal
        self.app = gui("Redes2 - P2P", window_size)
        self.app.setGuiPadding(10,10)

        # Preparación del interfaz
        self.app.addLabel("title", "Cliente Multimedia P2P - Redes2 ")
        self.app.addLabel("loggeduser", "Sesion no iniciada")
        self.app.addImage("video", "imgs/webcam.gif")

        # Registramos la función de captura de video
        # Esta misma función también sirve para enviar un vídeo
        self.cap = cv2.VideoCapture(0)
        self.app.setPollTime(20)
        self.app.registerEvent(self.capturaVideo)

        # Añadir los botones
        self.app.addButtons(["Conectar", "Espera", "Colgar", "Salir"], self.buttonsCallback)

        # Barra de estado
        # Debe actualizarse con información útil sobre la llamada (duración, FPS, etc...)
        self.app.addStatusbar(fields=2)
        #Bara de herramientas
        self.app.addToolbar(["FILE","CAMERA"], self.toolbarCallback, findIcon=True)
        self.app.setToolbarIcon("CAMERA","md-camera-photo")
        self.app.setStopFunction(self.stop)
        self.app.setStartFunction(self.on_startup)

        #Ventana de inicio de sesion
        self.app.startSubWindow("Login",modal=True) #Modal: Bloquea a la principal.

        self.app.addLabel("pad", "",0,0) #Padding above
        self.app.setPadding([30,0])

        self.app.setSticky('e')
        self.app.addLabel("user","Nick: ",1,0)
        self.app.addLabel("pass","Password: ",2,0)
        self.app.addLabel("tcp","Puerto de control (TCP): ",3,0)
        self.app.addLabel("udp","Puerto de video (UDP): ",4,0)

        self.app.setSticky('w')
        self.app.addEntry("userInput",1,2)
        self.app.addSecretEntry("passInput",2,2)
        self.app.addNumericEntry("tcpInput",3,2)
        self.app.addNumericEntry("udpInput",4,2)

        self.app.setPadding([20,20])
        self.app.addButton("Entrar", self.login,5,1)
        self.app.setStopFunction(self.app.stop) #Parar la ventana cierra la app.
        self.app.setPadding([0,0])
        self.app.stopSubWindow()

    def start(self):
        self.app.go()

    def stop(self):
        #Parar los hilos
        print("Aplicacion saliendo...")
        if self.connection_loop:
            control_listen_stop()
            self.connection_loop.join()
        if self.command_loop:
            control_incoming_stop()
            self.command_loop.join()
        server_quit()
        return True

    def on_startup(self):
        #Conexion a Discovery
        ret = server_init()
        if ret == -1:
            self.app.errorBox("Error", "No se ha podido establecer la conexion al servidor de descubrimiento.")
            self.app.stop()
            return

        #Tratemos de obtener datos preexistentes
        try:
            with open(user_filename, "r") as file:
                data = json.load(file)
                self.app.setEntry("userInput", data["username"],callFunction=False)
                self.app.setEntry("tcpInput", data["tcp_port"],callFunction=False)
                self.app.setEntry("udpInput", data["udp_port"],callFunction=False)
        except:
            print("Fichero de datos previo no encontrado. No se cargaran sugerencias previas.")

        self.app.showSubWindow("Login") #Mostramos ventana de login

    #Funcion que maneja el inicio de sesion
    def login(self):

        # Entrada del nick del usuario a conectar
        print("Comenzando registro de usuario.")
        register_nick = self.app.getEntry("userInput")
        password = self.app.getEntry("passInput")
        control_port = int(self.app.getEntry("tcpInput"))
        video_port = int(self.app.getEntry("udpInput"))

        invalid_port = False

        if control_port:
            if control_port>65535 or control_port < 1024:
                invalid_port = True
            control_port = str(control_port)
        if video_port:
            if video_port>65535 or video_port < 1024:
                invalid_port = True
            video_port = str(video_port)

        #Comprobamos rango
        if invalid_port:
            self.app.errorBox("Error", "El puerto introducido es invalido. Debe estar en el rango 1024-65535",parent="Login")
            return

        ip = socket.gethostbyname(socket.gethostname())

        if not register_nick or not password or not control_port or not video_port or not ip:
            self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Faltan datos.",parent="Login")
            return
        print("Tratando de registrar a " + register_nick + " con clave " + password + " puerto:" + control_port + " ip:" + ip + " puerto de video: " + video_port)
        ret = register_user(register_nick,password, ip, control_port)
        if not ret:
            #Error
            self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Error del servidor de descubrimiento.",parent="Login")
            return

        #Clave incorrecta
        if ret == -1:
            self.app.warningBox("Contraseña incorrecta.", "La contraseña es incorrecta. Por favor, introduzcala de nuevo.",parent="Login")
            return

        self.app.setLabel("loggeduser", "Sesion iniciada como: " + register_nick)
        self.listen_control_port = control_port

        #Iniciamos el buffer de video
        self.buffer_video = list()
        self.buffer_block = [True]

        #Iniciamos los sockets de video
        self.socket_video_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_video_rec = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_video_rec.bind(('',int(video_port)))

        #Hilos de recepcion
        self.connection_loop = threading.Thread(target=control_listen_loop, args = (self.listen_control_port,self.app))
        self.command_loop = threading.Thread(target=control_incoming_loop, args = (self.app,))
        self.connection_loop.start()
        self.command_loop.start()

        user_data = {"username":register_nick, "tcp_port":control_port, "udp_port":video_port}
        with open(user_filename, "w+") as file:
            json.dump(user_data,file, indent=4)

        #Mostrar ventana principal
        self.app.hideSubWindow("Login")


    # Función que captura el frame a mostrar en cada momento
    def capturaVideo(self):

        # Capturamos un frame de la cámara o del vídeo
        ret, frame = self.cap.read()
        frame_rec = np.array([]) #Frame capturado del otro

        #Bucle si el video acaba
        if not ret:
            self.cap = cv2.VideoCapture(self.currently_playing_file)
            ret,frame = self.cap.read()
            #Error
            if not ret:
                print("ERROR FATAL: Se ha perdido conexion de camara y de video.")
                self.app.errorBox("Error fatal", "El video que se estaba reproduciendo no se encuentra.")
                self.app.stop()
                return

        frame = cv2.resize(frame, (640,480))

        # Código que envia el frame a la red
        status = call_status()
        #TODO el contador num podria empezar como atributo a 0 y cada vez que se reinicie llamada (mirando el call status), reiniciarlo.
        if(status[0] != None and status[0] != "HOLD1" and status[0] != "HOLD2"):

            if(self.boolResetFrame == 1):
                self.num = 0
                self.boolResetFrame = 0
                self.startTime = time.time()
                self.receive_loop = threading.Thread(target=receive_frame, args = (self.socket_video_rec, self.buffer_video, self.buffer_block))
                self.receive_loop.start()
                print("Hilo de recepción de video iniciado.")

            #EN LLAMADA.
            self.app.setStatusbar("En llamada con: " + get_connected_username() ,field=0)

            #Enviamos el frame
            errorSend = send_frame(self.socket_video_send, (status[0],int(status[1])), frame, self.num, 50, "640x480", 40)
            if(errorSend == -1):
                print("Error sending message")
            self.num += 1

            #Popeamos el elemento a mostrar
            num, header, frame_rec = pop_frame(self.buffer_video,self.buffer_block)

            #Actualizamos la GUI
            if(len(header) >= 4):
                self.app.setStatusbar("Duracion: " + str(time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime))) + " FPS: " + str(header[3]) + " Resolution: " + str(header[2]) ,field=1)
            else:
                self.app.setStatusbar("Duracion: " + str(time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime))) ,field=1)

        elif status[0] == "HOLD1":
            frame_rec = cv2.imread("imgs/call_held.png")
            frame_rec = cv2.resize(frame_rec, (640,480))
            #EN ESPERA POR NUESTRA PARTE
            self.app.setStatusbar("Llamada en espera por " + get_username() ,field=0)
            self.app.setStatusbar("Duracion: " + time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime) ) ,field=1)

        elif status[0] == "HOLD2":
            frame_rec = cv2.imread("imgs/call_held.png")
            frame_rec = cv2.resize(frame_rec, (640,480))
            #EN ESPERA POR LA PARTE OPUESTA
            self.app.setStatusbar("Llamada en espera por " + get_connected_username() ,field=0)
            self.app.setStatusbar("Duracion: " + time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime)) ,field=1)

        elif get_connected_username() != None:
            frame_rec = cv2.imread("imgs/calling.jpg")
            frame_rec = cv2.resize(frame_rec, (640,480))
            #LLAMANDO
            self.app.setStatusbar("Llamando a " + get_connected_username(),field=0)

        else:
            #NO EN LLAMADA
            self.app.setStatusbar("Cliente listo para llamar.",field=0)
            self.app.setStatusbar("" ,field=1)
            if(self.boolResetFrame != 1):
                self.buffer_block = [True]
                self.boolResetFrame = 1
                self.buffer_video = list()
                self.socket_video_send.sendto(b'END_RECEPTION',('localhost',int(get_video_port())))
                self.receive_loop.join()
                print("Hilo de recepción de video recogido.")

        #Mostrar frame capturado
        if frame_rec.size != 0:
            #Frame pequeno
            frame_mini = cv2.resize(frame, (160,120))
            frame_compuesto = frame_rec
            frame_compuesto[0:frame_mini.shape[0], 0:frame_mini.shape[1]] = frame_mini
            frame = frame_compuesto

        cv2_im = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        img_tk = ImageTk.PhotoImage(Image.fromarray(cv2_im))
        self.app.setImageData("video", img_tk, fmt = 'PhotoImage')




    # Establece la resolución de la imagen capturada
    def setImageResolution(self, resolution):
        # Se establece la resolución de captura de la webcam
        # Puede añadirse algún valor superior si la cámara lo permite
        # pero no modificar estos
        if resolution == "LOW":
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 160)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 120)
        elif resolution == "MEDIUM":
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        elif resolution == "HIGH":
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    #Funcion que gestiona los callbacks de la barra de herramientas
    def toolbarCallback(self,button):
        if button == "FILE":
            f = self.app.openBox(title="Enviar video", dirName=None, fileTypes=[('videos','*.mp4'),('videos','*.avi'),('videos','*.mkv')],asFile=False)
            if f:
                try:
                    self.cap = cv2.VideoCapture(f)
                except cv2.error:
                    self.app.errorBox("Error abriendo fichero", "El fichero no es correcto.")
                    return
                self.currently_playing_file = f
        elif button == "CAMERA":
            if self.app.yesNoBox("Activar camara", "Quieres activar la videocamara?") == True:
                try:
                    self.cap = cv2.VideoCapture(0)
                except cv2.error:
                    self.app.errorBox("Error activando camara", "No se ha detectado ninguna camara")
                    return
                self.currently_playing_file = None


    # Función que gestiona los callbacks de los botones
    def buttonsCallback(self, button):

        if button == "Salir":

            #Si esta en llamada se cuelga.
            if call_status()[0] != None:
                self.buttonsCallback("Colgar")
            # Salimos de la aplicación
            self.app.stop()
        elif button == "Conectar":

            # Entrada del nick del usuario a conectar
            nick = self.app.textBox("Conexión",
                "Introduce el nick del usuario a buscar")

            if nick == get_username():
                self.app.warningBox("Advertencia", "No puedes llamarte a ti mismo.")
                return

            if nick == None:
                return

            #Para no bloquear la GUI, se llama en un hilo
            self.app.threadCallback(connect_to,self.call_callback,nick)

        elif button == "Colgar":
            ret = end_call()
            if ret == -1:
                self.app.warningBox("Advertencia.", "No está en llamada con ningún usuario.")
            if control_disconnect() != -1:
                self.app.infoBox("Desconexion", "Ha sido desconectado del destinatario.")

        elif button == "Espera":
            status = call_status()
            if status[0] == "HOLD1":
                #Ya estamos en espera. Desactivar.
                ret = set_on_hold(False)
                if ret == 0:
                    self.app.infoBox("Operación correcta.", "Se ha desactivado el modo espera.")
                else:
                    self.app.warningBox("Advertencia.", "No se ha podido desactivar el modo espera porque no esta en llamada.")
            elif status[0] != None:
                #Activar
                ret = set_on_hold(True)
                if ret == 0:
                    self.app.infoBox("Operación correcta.", "Se ha activado el modo espera.")
                else:
                    self.app.warningBox("Advertencia.", "No se ha podido desactivar el modo espera porque no esta en llamada.")
            else:
                self.app.warningBox("Advertencia.", "No se ha podido desactivar el modo espera porque no esta en llamada.")

    def call_callback(self,ret):
        if ret == -2:
            self.app.infoBox("Usuario ocupado", "El usuario al que llama está ocupado.")
        elif ret == -3:
            self.app.infoBox("Llamada rechazada", "El usuario indicado rechazó la llamada.")
        elif ret == -1:
            self.app.errorBox("Error durante la llamada", "No ha podido establecerse la conexión con el usuario indicado.")
        else:
            self.app.infoBox("Conectado", "Se ha conectado exitosamente al usuario objetivo.")

if __name__ == '__main__':

    vc = VideoClient("640x550")

    # Se inicializa en on_startup() para poder mostrar ventanas de info

    # Lanza el bucle principal del GUI
    # El control ya NO vuelve de esta función, por lo que todas las
    # acciones deberán ser gestionadas desde callbacks y threads
    vc.start()
