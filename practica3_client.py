'''
    practica3_client.py
    Programa principal que gestiona el cliente de video.
    Basado en el programa de prueba de los profesores de REDES2 @ UAM
    @author Miguel Gonzalez, Alejandro Bravo.
    @version 1.0
    @date 22-04-2020
'''

# import the libraries
from appJar import gui
from PIL import Image, ImageTk
import numpy as np
import cv2
import threading
import socket
import json
import time
from discovery import server_init, server_quit, register_user, query_user, list_users
from control import *
from video import *
import requests #Para hacer la peticion de ip externa

class VideoClient(object):

    #PARAMETROS DE CONTROL DEL CLIENTE DE VIDEO

    connection_loop = None #Hilo que despacha las conexiones entrantes
    command_loop = None #Hilo que atiende a los comandos de llamada entrantes
    frame_send_loop = None #Hilo que envia los frames al ritmo correcto
    frame_recv_loop = None #Hilo que recibe los frames al ritmo correcto
    nick = None #Nombre de usuario
    listen_control_port = "10000" #Puerto de escucha para control
    boolResetFrame = 1 #Indica si han de resetearse los campos propios de la llamada la siguiente vez que se actualice frame.
    socket_video_send = None #Socket UDP para enviar video
    socket_video_rec = None #Socket UDP para recibir video
    num = 0 #Numero de secuencia del frame actual
    buffer_video = None #Buffer con los frames de video
    buffer_block = [True] #Indicara al buffer si puede sacar frames o no. Solo lo levantaremos cuando este parcialmente lleno.
    currently_playing_file = None #Nombre del fichero que se esta enviando actualmente.
    fps_send = [30] #FPS para el video saliente
    fps_recv = 20 #FPS para el video entrante
    quality_send = [50] #Calidad de compresión del video saliente
    resolution_send = ["640x480"] # Resolucion a la que se envía el video
    packets_lost_total = [0] #Numero de paquetes perdidos
    cap_frame = np.array([]) #Frame nuestro que se captura a ritmo de fps_send
    rec_frame = np.array([]) #Ultimo frame recibido, se actualiza a ritmo de fps_recv
    cap_frame_lock = threading.Lock() #Lock para captura de video
    rec_frame_lock = threading.Lock() #Lock para recepcion de video
    update_screen_lock = threading.Lock() #Para evitar que receptor y emisor actualicen la pantalla a la vez.
    program_quit = False #Indica si han solicitado cerrar el programa.

    def __init__(self, window_size):
        '''
        Nombre: __init__
        Descripcion: Constructor del cliente de video
        Argumentos: window_size: Tamano de la ventana.
        '''
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

        # Añadir los botones
        self.app.addButtons(["Conectar", "Espera", "Colgar", "Salir"], self.buttonsCallback)

        # Barra de estado
        # Debe actualizarse con información útil sobre la llamada (duración, FPS, etc...)
        self.app.addStatusbar(fields=3)
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
        self.app.addLabel("ip","Direccion IP: ",5,0)
        self.app.addLabel("ipWarn","(La IP puede dejarse en blanco para utilizar la IP local)",6,2)

        self.app.setSticky('w')
        self.app.addEntry("userInput",1,2)
        self.app.addSecretEntry("passInput",2,2)
        self.app.addNumericEntry("tcpInput",3,2)
        self.app.addNumericEntry("udpInput",4,2)
        self.app.addEntry("ipInput",5,2)

        self.app.setPadding([20,20])
        self.app.addButton("Entrar", self.login,7,1)
        self.app.setStopFunction(self.app.stop) #Parar la ventana cierra la app.
        self.app.setPadding([0,0])
        self.app.stopSubWindow()

        # Definicion de la ventana de elegir usuario para llamada:
        self.app.startSubWindow("Iniciar llamada",modal=True) #Modal: Bloquea a la principal.

        self.app.addLabel("pad2", "",0,0) #Padding above
        self.app.setPadding([30,0])

        self.app.setSticky('e')
        self.app.addLabel("calleeNick","Llamar a: ",1,0)
        self.app.addLabel("listInfo","Usuarios registrados:",2,0)

        self.app.setSticky('w')
        self.app.addEntry("calleeNickInput",1,1)
        self.app.addListBox("nicksList",["Cargando..."],2,1)

        #Handler
        self.app.setListBoxChangeFunction("nicksList", self.list_handler)

        self.app.setPadding([20,20])
        self.app.addButton("Llamar", self.init_call,3,1)
        self.app.setPadding([0,0])
        self.app.stopSubWindow()

    def start(self):
        '''
        Nombre: start
        Descripcion: Arranca el cliente y realiza todas las conexiones e hilos necesarios.
        '''
        self.app.go()

    def async_cleaning(self):
        '''
        Nombre: async_cleaning
        Descripcion: Limpia los hilos y conexiones. Esta pensado para llamar de manera asincrona
                     antes de cerrar el cliente, para hacerlo de forma limpia.
                     Debe llamarse asincronamente para no bloquear la GUI, que tiene lugar en la limpieza.
        '''
        #Parar los hilos
        print("Aplicacion saliendo...")
        self.program_quit = True
        if self.frame_send_loop:
            self.frame_send_loop.join()
        if self.frame_recv_loop:
            self.frame_recv_loop.join()
        if self.connection_loop:
            control_listen_stop()
            self.connection_loop.join()
        if self.command_loop:
            control_incoming_stop()
            self.command_loop.join()
        server_quit()
        #Notificar a la GUI de que hay que parar.
        self.app.stop()

    def stop(self):
        '''
        Nombre: stop
        Descripcion: Manejador para el cierre de la aplicacion. Realiza primero una limpieza asincrona.
        '''
        #La parada la hacemos asincrona porque hay algunos elementos que para
        #limpiarse necesitan del hilo principal de la gui, que esta ocupado en
        #esta funcion. Esto se podria arreglar usando la cola de eventos
        #de appJar, pero no esta pensada ni de lejos para video. Su ratio
        #de refresco es 10 veces por segundo, y hemos logrado incrementarlo
        #mirando el codigo de appJar (hay una variable privada que podemos modificar)
        #pero aun asi no es suficiente.
        if not self.program_quit:
            self.app.thread(self.async_cleaning)
            return False
        return True

    def on_startup(self):
        '''
        Nombre: on_startup
        Descripcion: Manejador de inicio de la aplicacion. Se ejecuta al comenzar la app.
        '''
        #Conexion a Discovery
        ret = server_init()
        if ret == -1:
            self.app.errorBox("Error", "No se ha podido establecer la conexion al servidor de descubrimiento.")
            self.app.stop()
            return

        #Obtenemos IP externa
        try:
            ip_req = requests.get('http://ip.jsontest.com/').json()
            self.app.setEntry("ipInput", ip_req["ip"], callFunction=False)
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            print("ADVERTENCIA: Error obteniendo IP desde recurso externo. El usuario debera introducirla.")

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
        '''
        Nombre: login
        Descripcion: Registra al usuario en la aplicacion y arranca todos los hilos necesarios para gestionar
        la sesion.
        '''
        # Entrada del nick del usuario a conectar
        print("Comenzando registro de usuario.")
        register_nick = self.app.getEntry("userInput")
        password = self.app.getEntry("passInput")
        control_port = int(self.app.getEntry("tcpInput"))
        video_port = int(self.app.getEntry("udpInput"))
        ip = self.app.getEntry("ipInput")

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

        if ip == None or ip == "":
            #Ponemos la IP local
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
        self.frame_send_loop = threading.Thread(target=self.enviaVideo)
        self.frame_recv_loop = threading.Thread(target=self.capturaVideo)
        self.frame_send_loop.start()
        self.frame_recv_loop.start()

        user_data = {"username":register_nick, "tcp_port":control_port, "udp_port":video_port}
        with open(user_filename, "w+") as file:
            json.dump(user_data,file, indent=4)

        #Mostrar ventana principal
        self.app.hideSubWindow("Login")

    # Función que envia el frame a mostrar en cada momento
    def enviaVideo(self):
        '''
        Nombre: enviaVideo
        Descripcion: Bucle para enviar video que se ejecuta asincronamente, cada
        1/FPS_ENVIO segundos. Tambien se ocupa de mostrar en la pantalla nuestra imagen.
        '''
        while not self.program_quit:
            # Capturamos un frame de la cámara o del vídeo
            ret, frame = self.cap.read()
            #Bucle si el video acaba
            if not ret:
                self.cap = cv2.VideoCapture(self.currently_playing_file)
                ret,frame = self.cap.read()
                #Error
                if not ret:
                    self.app.errorBox("Error fatal", "El video/camara que se estaba reproduciendo no se encuentra. Puede deberse a que este en uso por otra aplicacion.")
                    self.app.stop()
                    return
            frame = cv2.resize(frame, (640,480))
            # Código que envia el frame a la red
            status = call_status()
            if(status[0] != None and status[0] != "HOLD1" and status[0] != "HOLD2"):
                #Enviamos el frame
                errorSend = send_frame(self.socket_video_send, (status[0],int(status[1])), frame, self.num, self.quality_send[0],self.resolution_send[0], self.fps_send[0])
                if(errorSend == -1):
                    print("Error sending message")
                self.num += 1
            with self.cap_frame_lock:
                self.cap_frame = np.copy(frame)
            string_field1 = "Video propio: " + str(self.fps_send[0]) + " FPS"
            string_field1 += " Quality compression: " + str(self.quality_send[0])
            string_field1 += " Resolution: " + self.resolution_send[0]
            self.app.setStatusbar( string_field1 ,field=1)
            self.updateScreen()
            time.sleep(1/self.fps_send[0])
        #self.app.after(int(1/self.fps_send*1000), self.enviaVideo)
        print("Hilo de procesado de video saliente recogido.")

    # Función que captura el frame a mostrar en cada momento
    def capturaVideo(self):
        '''
        Nombre: capturaVideo
        Descripcion: Bucle para capturar video que se ejecuta asincronamente, cada
        1/FPS_RECEPCION segundos. Si esta en llamada, lanzara un sub-hilo que recibira
        en todo momento frames del emisor, llenando un buffer, para que poder extraer de
        dicho buffer al ritmo deseado.
        '''
        while not self.program_quit:
            frame_rec = np.array([])

            connecting_to = get_connected_username()

            # Código que envia el frame a la red
            status = call_status()
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

                #Popeamos el elemento a mostrar
                num, header, frame_rec = pop_frame(self.buffer_video,self.buffer_block, self.quality_send, self.fps_send, self.packets_lost_total)

                #Actualizamos la GUI
                if(len(header) >= 4):
                    string = "Duracion: " + str(time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime)))
                    string += " FPS: " + str(header[3])
                    string += " Resolution: " + str(header[2])
                    string += " Frames perdidos: " + str(self.packets_lost_total[0])
                    self.app.setStatusbar(string ,field=2)
                    self.fps_recv = int(header[3])
                else:
                    self.app.setStatusbar("Duracion: " + str(time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime))) ,field=2)

            elif status[0] == "HOLD1":
                frame_rec = cv2.imread("imgs/call_held.png")
                frame_rec = cv2.resize(frame_rec, (640,480))
                #EN ESPERA POR NUESTRA PARTE
                self.app.setStatusbar("Llamada en espera por " + get_username() ,field=0)
                self.app.setStatusbar("Duracion: " + time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime) ) ,field=2)

            elif status[0] == "HOLD2":
                frame_rec = cv2.imread("imgs/call_held.png")
                frame_rec = cv2.resize(frame_rec, (640,480))
                #EN ESPERA POR LA PARTE OPUESTA
                self.app.setStatusbar("Llamada en espera por " + connecting_to ,field=0)
                self.app.setStatusbar("Duracion: " + time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime)) ,field=2)

            elif connecting_to != None:
                frame_rec = cv2.imread("imgs/calling.jpg")
                frame_rec = cv2.resize(frame_rec, (640,480))
                #LLAMANDO
                self.app.setStatusbar("Llamando a " + connecting_to,field=0)

            else:
                #NO EN LLAMADA
                self.app.setStatusbar("Cliente listo para llamar.",field=0)
                self.app.setStatusbar("" ,field=2)
                if(self.boolResetFrame != 1):
                    self.buffer_block = [True]
                    self.boolResetFrame = 1
                    self.fps_recv = 30
                    self.quality_send[0] = 50
                    self.packets_lost_total[0] = 0
                    self.rec_frame = np.array([])
                    self.buffer_video = list()
                    self.socket_video_send.sendto(b'END_RECEPTION',('localhost',int(get_video_port())))
                    self.receive_loop.join()
                    print("Hilo de recepción de video recogido.")

            with self.rec_frame_lock:
                self.rec_frame = np.copy(frame_rec)

            self.updateScreen()
            time.sleep(1/self.fps_recv)
        #self.app.after(int(1/self.fps_recv*1000), self.capturaVideo)

        #Fin del hilo:

        if(self.boolResetFrame != 1):
            self.buffer_block = [True]
            self.boolResetFrame = 1
            self.fps_recv = 30
            self.rec_frame = np.array([])
            self.buffer_video = list()
            self.socket_video_send.sendto(b'END_RECEPTION',('localhost',int(get_video_port())))
            self.receive_loop.join()
            print("Hilo de recepción de video recogido.")
        print("Hilo de procesado de video entrante recogido.")

    #Actualiza la pantalla con los frames que haya
    def updateScreen(self):
        '''
        Nombre: updateScreen
        Descripcion: Con los frames que haya capturado cada hilo (emisor/receptor), los
        pinta en la pantalla.
        '''
        with self.rec_frame_lock:
            frame_rec = np.copy(self.rec_frame)
        with self.cap_frame_lock:
            frame = np.copy(self.cap_frame)

        #Mostrar frame capturado
        if frame_rec.size != 0:
            #Frame pequeno
            frame_mini = cv2.resize(frame, (160,120))
            frame_compuesto = frame_rec
            frame_compuesto[0:frame_mini.shape[0], 0:frame_mini.shape[1]] = frame_mini
            frame = frame_compuesto

        if frame.size != 0:
            cv2_im = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            img_tk = ImageTk.PhotoImage(Image.fromarray(cv2_im))
            with self.update_screen_lock:
                self.app.setImageData("video", img_tk, fmt = 'PhotoImage')

    # Establece la resolución de la imagen capturada
    def setImageResolution(self, resolution):
        '''
        Nombre: setImageResolution
        Descripcion: Ajusta la resolucion con la que se captura la imagen.
        Argumentos: resolution puede ser LOW MEDIUM o HIGH.
        '''
        if resolution == "LOW":
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 160)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 120)
        elif resolution == "MEDIUM":
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        elif resolution == "HIGH":
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    def toolbarCallback(self,button):
        '''
        Nombre: toolbarCallback
        Descripcion: Al pulsar un boton de la barra de herramientas se ejecuta.
        Argumentos: button - cadena con el nombre del boton pulsado
        '''
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
        '''
        Nombre: buttonsCallback
        Descripcion: Al pulsar un boton se ejecuta.
        Argumentos: button - cadena con el nombre del boton pulsado
        '''
        if button == "Salir":

            #Si esta en llamada se cuelga.
            if call_status()[0] != None:
                self.buttonsCallback("Colgar")
            # Salimos de la aplicación
            self.app.stop()
        elif button == "Conectar":

            #Hay que poblar la lista de usuarios, segundo plano para no bloquear la UI:
            self.app.thread(self.populate_list)

            #Mostramos la ventana para llamar.
            self.app.showSubWindow("Iniciar llamada")

        elif button == "Colgar":
            ret = end_call()
            if ret == -1:
                self.app.warningBox("Advertencia.", "No está en llamada con ningún usuario.")
                return
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

    #Llama a alguien
    def init_call(self):
        '''
        Nombre: init_call
        Descripcion: Inicia una llamada con el usuario que se haya indicado en la ventana correspondiente.
        La llamada se iniciara asincronamente para no bloquear el GUI.
        '''
        nick = self.app.getEntry("calleeNickInput")
        self.app.hideSubWindow("Iniciar llamada")
        if nick == get_username():
            self.app.warningBox("Advertencia", "No puedes llamarte a ti mismo.")
            return
        if nick == None or nick == "":
            self.app.warningBox("Advertencia", "No has introducido usuario.")
            return
        #Para no bloquear la GUI, se llama en un hilo
        self.app.threadCallback(connect_to,self.call_callback,nick)

    def call_callback(self,ret):
        '''
        Nombre: call_callback
        Descripcion: Se ejecuta cuando la llamada que se estaba intentando iniciar asincronamente devuelve un resultado.
        Arugmentos: ret - resultado del establecimiento de la llamada.
        '''
        if ret == -2:
            self.app.thread(self.app.infoBox,"Usuario ocupado", "El usuario al que llama está ocupado.")
        elif ret == -3:
            self.app.thread(self.app.infoBox,"Llamada rechazada", "El usuario indicado rechazó la llamada.")
        elif ret == -1:
            self.app.thread(self.app.errorBox,"Error durante la llamada", "No ha podido establecerse la conexión con el usuario indicado.")
        else:
            self.app.thread(self.app.infoBox,"Conectado", "Se ha conectado exitosamente al usuario objetivo.")

    def list_handler(self):
        '''
        Nombre: list_handler
        Descripcion: Se ejecuta cuando el usuario seleccione un nick de la lista.
        '''
        inputs = self.app.getListBox("nicksList")
        if len(inputs) > 0:
            nick = inputs[0]
            self.app.setEntry("calleeNickInput", nick)

    def populate_list(self):
        '''
        Nombre: populate_list
        Descripcion: Funcion pensada para rellenar la lista de usuarios de forma asincrona.
        '''
        users = list_users()
        if users == None:
            print("Error obteniendo listado de usuarios.")
            return

        self.app.updateListBox("nicksList", [e[0] for e in users], select=False)

#PROGRAMA PRINCIPAL

if __name__ == '__main__':

    vc = VideoClient("1280x720")

    # Se inicializa en on_startup() para poder mostrar ventanas de info

    # Lanza el bucle principal del GUI
    # El control ya NO vuelve de esta función, por lo que todas las
    # acciones deberán ser gestionadas desde callbacks y threads
    vc.start()
