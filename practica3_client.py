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
from discovery import Discovery
from control import Control
from video import VideoBuffer
from config import config_parser
import requests #Para hacer la peticion de ip externa

class VideoClient(object):

    #PARAMETROS DE CONTROL DEL CLIENTE DE VIDEO

    discovery = None #Objeto que gestiona la conexion al server de descubrimiento
    connection_loop = None #Hilo que despacha las conexiones entrantes
    command_loop = None #Hilo que atiende a los comandos de llamada entrantes
    frame_send_loop = None #Hilo que envia los frames al ritmo correcto
    frame_recv_loop = None #Hilo que recibe los frames al ritmo correcto
    nick = None #Nombre de usuario
    listen_control_port = "10000" #Puerto de escucha para control. Lo ajusta el usuario con la interfaz.
    boolResetFrame = 1 #Indica si han de resetearse los campos propios de la llamada la siguiente vez que se actualice frame.
    socket_video_send = None #Socket UDP para enviar video
    socket_video_rec = None #Socket UDP para recibir video
    num = 0 #Numero de secuencia del frame actual
    buffer_video = None #Objeto de buffer de video
    currently_playing_file = None #Nombre del fichero que se esta enviando actualmente.
    fps_send = [30] #FPS para el video saliente
    fps_send_min = 20 #FPS minimos posibles que el QoS puede poner
    fps_send_max = 60 #FPS maximos posibles que el QoS puede poner
    fps_recv = 20 #FPS para el video entrante
    quality_send = [50] #Calidad de compresión del video saliente
    resolution_send = ["640x480"] # Resolucion a la que se envía el video
    resolution_send_old = ["640x480"]
    packets_lost_total = [0] #Numero de paquetes perdidos
    cap_frame = np.array([]) #Frame nuestro que se captura a ritmo de fps_send
    rec_frame = np.array([]) #Ultimo frame recibido, se actualiza a ritmo de fps_recv
    cap_frame_lock = threading.Lock() #Lock para captura de video
    rec_frame_lock = threading.Lock() #Lock para recepcion de video
    update_screen_lock = threading.Lock() #Para evitar que receptor y emisor actualicen la pantalla a la vez.
    program_quit = False #Indica si han solicitado cerrar el programa.
    config = None #Objeto con parametros de configuracion
    control = None #Objeto del modulo de control

    def __init__(self, window_size):
        '''
        Nombre: __init__
        Descripcion: Constructor del cliente de video
        Argumentos: window_size: Tamano de la ventana.
        '''

        #Creamos el objeto de configuracion
        self.config = config_parser()

        #Creamos el objeto de buffer de video
        self.buffer_video = VideoBuffer(self.config)

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

        #FPS minimo y maximo para el QoS
        self.fps_send_max = int(self.cap.get(cv2.CAP_PROP_FPS))
        self.fps_send_min = self.fps_send_min // 2
        self.fps_send = [self.fps_send_max]

        # Añadir los botones
        self.app.addButtons(["Conectar", "Espera", "Colgar", "Salir"], self.buttonsCallback)
        self.app.enableButton("Conectar")
        self.app.disableButton("Espera")
        self.app.disableButton("Colgar")


        # Barra de estado
        # Debe actualizarse con información útil sobre la llamada (duración, FPS, etc...)
        self.app.addStatusbar(fields=3,side="LEFT")
        self.app.setStatusbarWidth(35,field=0)
        self.app.setStatusbarWidth(50,field=1)
        self.app.setStatusbarWidth(60,field=2)
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
            self.control.control_listen_stop()
            self.connection_loop.join()
        if self.command_loop:
            self.control.control_incoming_stop()
            self.command_loop.join()
        if self.socket_video_send:
            self.socket_video_send.close()
        if self.socket_video_rec:
            self.socket_video_rec.close()
        if self.discovery:
            #Desconexion de discovery
            self.discovery.server_quit()
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
        try:
            self.discovery = Discovery(self.config.server_ip, self.config.server_port)
        except Exception as e:
            print(e)
            self.app.errorBox("Error", "No se ha podido establecer la conexion al servidor de descubrimiento.")
            self.app.stop()
            return

        self.control = Control(self.discovery, self.config.call_timeout, self.config.user_filename)

        #Obtenemos IP externa
        try:
            ip_req = requests.get('https://api.ipify.org?format=json').json()
            self.app.setEntry("ipInput", ip_req["ip"], callFunction=False)
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            print("ADVERTENCIA: Error obteniendo IP desde recurso externo. El usuario debera introducirla.")

        #Tratemos de obtener datos preexistentes
        try:
            with open(self.config.user_filename, "r") as file:
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
        # Entrada de los datos del usuario a conectar
        print("Comenzando registro de usuario.")
        register_nick = self.app.getEntry("userInput")
        password = self.app.getEntry("passInput")
        control_port = int(self.app.getEntry("tcpInput"))
        video_port = int(self.app.getEntry("udpInput"))
        ip = self.app.getEntry("ipInput")


        #Comprobamos si los puertos introducidos son correctos
        invalid_port = False
        if control_port:
            if control_port>65535 or control_port < 1024:
                invalid_port = True
            control_port = str(control_port)
        if video_port:
            if video_port>65535 or video_port < 1024:
                invalid_port = True
            video_port = str(video_port)
        if invalid_port:
            self.app.errorBox("Error", "El puerto introducido es invalido. Debe estar en el rango 1024-65535",parent="Login")
            return

        #Si no se introdujo IP
        if ip == None or ip == "":
            #Ponemos la IP local
            ip = socket.gethostbyname(socket.gethostname())

        #Faltan datos
        if not register_nick or not password or not control_port or not video_port or not ip:
            self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Faltan datos.",parent="Login")
            return

        #Realizamos el registro en el discovery
        print("Tratando de registrar a " + register_nick + " con clave " + password + " puerto:" + control_port + " ip:" + ip + " puerto de video: " + video_port)
        ret = self.discovery.register_user(register_nick,password, ip, control_port)
        if not ret:
            #Error
            self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Error del servidor de descubrimiento.",parent="Login")
            return

        #Clave incorrecta, la volvemos a pedir.
        if ret == -1:
            self.app.warningBox("Contraseña incorrecta.", "La contraseña es incorrecta. Por favor, introduzcala de nuevo.",parent="Login")
            return

        #Ajustamos la informacion indicando quien ha iniciado la sesion
        self.app.setLabel("loggeduser", "Sesion iniciada como: " + register_nick)
        self.listen_control_port = control_port

        #Iniciamos los sockets de video
        self.socket_video_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_video_rec = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_video_rec.bind(('',int(video_port)))

        #Hilos de recepcion y envio:
        #CONEXION: Atiende conexiones nuevas que entren gestionando los intentos de llamada (ACCEPT/DENY/BUSY)
        self.connection_loop = threading.Thread(target=self.control.control_listen_loop, args = (self.listen_control_port,self.app))
        #COMANDOS: Responde a los comandos que entren a traves de una llamada entrante. Esta bloqueado mientras no hay llamadas.
        self.command_loop = threading.Thread(target=self.control.control_incoming_loop, args = (self.app,))
        self.connection_loop.start()
        self.command_loop.start()
        #ENVIO: Muestra por pantalla (y si es necesario envia por la red) los frames al ritmo adecuado
        self.frame_send_loop = threading.Thread(target=self.enviaVideo)
        #RECEPCION: Hilo que a ritmo de FPS-recv actualiza el frame entrante.
        self.frame_recv_loop = threading.Thread(target=self.capturaVideo)
        self.frame_send_loop.start()
        self.frame_recv_loop.start()

        #Almacenamos datos relevantes del usuario en formato JSON
        user_data = {"username":register_nick, "tcp_port":control_port, "udp_port":video_port}
        with open(self.config.user_filename, "w+") as file:
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

            #Tiempo actual para mayor precision en los FPS
            send_start_time = time.time()

            #Reajustamos la resolucion en caso de que sea necesario
            if(self.resolution_send[0] != self.resolution_send_old[0]):
                self.setImageResolution(self.resolution_send[0])
                self.resolution_send_old[0] = self.resolution_send[0]

            # Capturamos un frame de la cámara o del vídeo
            ret, frame = self.cap.read()
            #Bucle si el video acaba o si la camara se desconecta como consecuencia de un cambio de conexion
            if not ret:
                #Se reestablece la conexion con el video o camara
                if self.currently_playing_file:
                    self.cap = cv2.VideoCapture(self.currently_playing_file)
                else:
                    self.cap = cv2.VideoCapture(0)
                #Se vuelve a intentar
                ret, frame = self.cap.read()
                #Error
                if not ret:
                    self.app.errorBox("Error fatal", "El video/camara que se estaba reproduciendo no se encuentra. Puede deberse a que este en uso por otra aplicacion.")
                    self.app.stop()
                    return

            #Reescalado para mostrar en la GUI
            frame = cv2.resize(frame, (640,480))

            # Código que envia el frame a la red en caso de que se este en llamada
            status = self.control.call_status()
            if(status[0] != None and status[0] != "HOLD1" and status[0] != "HOLD2"):
                #Enviamos el frame
                errorSend = self.buffer_video.send_frame(self.socket_video_send, (status[0],int(status[1])), frame, self.num, self.quality_send[0],self.resolution_send[0], self.fps_send[0])
                if(errorSend == -1):
                    print("Error sending message")
                self.num += 1

            #Almacenamos finalmente el frame
            with self.cap_frame_lock:
                self.cap_frame = frame

            #Actualizacion de informacion
            string_field1 = "Video propio: " + str(self.fps_send[0]) + " FPS"
            string_field1 += " Compresion: " + str(self.quality_send[0]) + "%"
            string_field1 += " Resolucion: " + self.resolution_send[0]
            self.app.setStatusbar( string_field1 ,field=1)

            #Repintar la pantalla
            self.updateScreen()

            #Pausa el tiempo que quede para mandar a ritmo FPS_send
            remaining = 1/self.fps_send[0] - (time.time() - send_start_time)
            if(remaining > 0):
                time.sleep(remaining)

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

            #Frame que nos llega
            frame_rec = np.array([])

            #Tiempo actual para mayor precision en los FPS
            receive_start_time = time.time()

            #Con quien estamos conectados
            connecting_to = self.control.get_connected_username()

            # Código que recoge el frame a imprimir por pantalla
            status = self.control.call_status()
            if(status[0] != None and status[0] != "HOLD1" and status[0] != "HOLD2"):

                #Si es el primer tick en el que se ha entrado aqui, preparar lo necesario
                if(self.boolResetFrame == 1):
                    self.app.disableButton("Conectar")
                    self.app.enableButton("Espera")
                    self.app.enableButton("Colgar")
                    self.boolResetFrame = 0
                    self.startTime = time.time()
                    #Hilo de RECOGIDA: Recoge paquetes de video entrantes continuamente, de manera asincrona.
                    self.receive_loop = threading.Thread(target=self.buffer_video.receive_frame, args = (self.socket_video_rec,))
                    self.receive_loop.start()
                    print("Hilo de recepción de video iniciado.")

                #Actualizar informacion
                self.app.setStatusbar("En llamada con: " + self.control.get_connected_username() ,field=0)

                #Popeamos el elemento a mostrar
                _, header, frame_rec = self.buffer_video.pop_frame(self.quality_send, self.fps_send, self.resolution_send ,self.packets_lost_total,self.fps_send_min,self.fps_send_max)

                #Actualizamos la GUI
                if(len(header) >= 4):
                    string = "Duracion: " + str(time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime)))
                    string += " FPS: " + str(header[3])
                    string += " Resolucion: " + str(header[2])
                    string += " Perdidos: " + str(self.packets_lost_total[0])
                    self.app.setStatusbar(string ,field=2)
                    self.fps_recv = int(header[3])
                else:
                    #Aun no hay frames suficientes en el buffer: icono de carga
                    self.app.setStatusbar("Duracion: " + str(time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime))) ,field=2)
                    frame_rec = cv2.imread("imgs/loading_video.png")

            elif status[0] == "HOLD1":
                #EN ESPERA POR NUESTRA PARTE
                frame_rec = cv2.imread("imgs/call_held.png")
                self.app.setStatusbar("Llamada en espera por " + self.control.get_username() ,field=0)
                self.app.setStatusbar("Duracion: " + time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime) ) ,field=2)

            elif status[0] == "HOLD2":
                #EN ESPERA POR LA PARTE OPUESTA
                frame_rec = cv2.imread("imgs/call_held.png")
                self.app.setStatusbar("Llamada en espera por " + connecting_to ,field=0)
                self.app.setStatusbar("Duracion: " + time.strftime('%H:%M:%S',time.gmtime(time.time() - self.startTime)) ,field=2)

            elif connecting_to != None:
                #LLAMANDO
                frame_rec = cv2.imread("imgs/calling.jpg")
                self.app.setStatusbar("Llamando a " + connecting_to,field=0)
                self.app.disableButton("Conectar")
                self.app.disableButton("Espera")
                self.app.disableButton("Colgar")

            else:
                #NO EN LLAMADA
                self.app.setStatusbar("Cliente listo para llamar.",field=0)
                self.app.setStatusbar("" ,field=2)

                #Si es el primer tick que se entra aqui tras una llamada, finalizamos todos los recursos asociados a la misma.
                if(self.boolResetFrame != 1):

                    #Parar hilo de RECOGIDA
                    self.socket_video_send.sendto(b'END_RECEPTION',('localhost',int(self.control.get_video_port())))
                    self.receive_loop.join()

                    #Reinicio de parametros
                    self.boolResetFrame = 1
                    self.fps_recv = 30
                    self.num = 0
                    self.quality_send[0] = 50
                    self.packets_lost_total[0] = 0
                    self.rec_frame = np.array([])
                    
                    #Vaciado del buffer
                    self.buffer_video.empty_buffer()

                    #Reactivar botones
                    self.app.enableButton("Conectar")
                    self.app.disableButton("Espera")
                    self.app.disableButton("Colgar")
                    print("Hilo de recepción de video recogido.")

            #Una vez obtenido el frame entrante, lo reescalamos para que entre en la gui.
            if frame_rec.size != 0:
                frame_rec = cv2.resize(frame_rec, (640,480))

            #Lo almacenamos
            with self.rec_frame_lock:
                self.rec_frame = frame_rec

            #Actualizamos la pantalla
            self.updateScreen()

            #Pausa el tiempo que quede para mandar a ritmo FPS_recv
            remaining = 1/self.fps_recv - (time.time() - receive_start_time)
            if(remaining > 0):
                time.sleep(remaining)

        #Fin del hilo: liberar recursos, si los hubiese.

        if(self.boolResetFrame != 1):
            self.boolResetFrame = 1
            self.fps_recv = 30
            self.rec_frame = np.array([])
            self.buffer_video.empty_buffer()
            self.socket_video_send.sendto(b'END_RECEPTION',('localhost',int(self.control.get_video_port())))
            self.receive_loop.join()
            print("Hilo de recepción de video recogido.")
        print("Hilo de procesado de video entrante recogido.")

    def updateScreen(self):
        '''
        Nombre: updateScreen
        Descripcion: Con los frames que haya capturado cada hilo (emisor/receptor), los
        pinta en la pantalla.
        '''
        with self.rec_frame_lock:
            frame_rec = self.rec_frame
        with self.cap_frame_lock:
            frame = self.cap_frame

        #Mostrar frame capturado
        if frame_rec.size != 0 and frame.size != 0:
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
        Argumentos: Resolution en achura x altura
        '''

        resolution = resolution.split('x')

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(resolution[0]))
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(resolution[1]))

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
                #Acutalizar umbral de FPS
                self.fps_send_max = round(self.cap.get(cv2.CAP_PROP_FPS))
                self.fps_send_min = self.fps_send_max
                self.fps_send = [self.fps_send_max]
        elif button == "CAMERA":
            if self.app.yesNoBox("Activar camara", "Quieres activar la videocamara?") == True:
                try:
                    self.cap = cv2.VideoCapture(0)
                except cv2.error:
                    self.app.errorBox("Error activando camara", "No se ha detectado ninguna camara")
                    return
                self.currently_playing_file = None
                #Acutalizar umbral de FPS
                self.fps_send_max = int(self.cap.get(cv2.CAP_PROP_FPS))
                self.fps_send_min = self.fps_send_max // 2
                self.fps_send = [self.fps_send_max]

    def buttonsCallback(self, button):
        '''
        Nombre: buttonsCallback
        Descripcion: Al pulsar un boton se ejecuta.
        Argumentos: button - cadena con el nombre del boton pulsado
        '''
        if button == "Salir":

            #Si esta en llamada se cuelga.
            if self.control.call_status()[0] != None:
                self.buttonsCallback("Colgar")
            # Salimos de la aplicación
            self.app.stop()
        elif button == "Conectar":

            #Hay que poblar la lista de usuarios, segundo plano para no bloquear la UI:
            self.app.thread(self.populate_list)

            #Mostramos la ventana para llamar.
            self.app.showSubWindow("Iniciar llamada")

        elif button == "Colgar":
            ret = self.control.end_call()
            if ret == -1:
                self.app.warningBox("Advertencia.", "No está en llamada con ningún usuario.")
                return
            if self.control.control_disconnect() != -1:
                self.app.infoBox("Desconexion", "Ha sido desconectado del destinatario.")

        elif button == "Espera":
            status = self.control.call_status()
            if status[0] == "HOLD1":
                #Ya estamos en espera. Desactivar.
                ret = self.control.set_on_hold(False)
                if ret == 0:
                    self.app.infoBox("Operación correcta.", "Se ha desactivado el modo espera.")
                else:
                    self.app.warningBox("Advertencia.", "No se ha podido desactivar el modo espera porque no esta en llamada.")
            elif status[0] != None:
                #Activar
                ret = self.control.set_on_hold(True)
                if ret == 0:
                    self.app.infoBox("Operación correcta.", "Se ha activado el modo espera.")
                else:
                    self.app.warningBox("Advertencia.", "No se ha podido desactivar el modo espera porque no esta en llamada.")
            else:
                self.app.warningBox("Advertencia.", "No se ha podido desactivar el modo espera porque no esta en llamada.")

    def init_call(self):
        '''
        Nombre: init_call
        Descripcion: Inicia una llamada con el usuario que se haya indicado en la ventana correspondiente.
        La llamada se iniciara asincronamente para no bloquear el GUI.
        '''
        nick = self.app.getEntry("calleeNickInput")
        self.app.hideSubWindow("Iniciar llamada")
        if nick == self.control.get_username():
            self.app.warningBox("Advertencia", "No puedes llamarte a ti mismo.")
            return
        if nick == None or nick == "":
            self.app.warningBox("Advertencia", "No has introducido usuario.")
            return
        #Para no bloquear la GUI, se llama en un hilo
        self.app.threadCallback(self.control.connect_to,self.call_callback,nick)

    def call_callback(self,ret):
        '''
        Nombre: call_callback
        Descripcion: Se ejecuta cuando la llamada que se estaba intentando iniciar asincronamente devuelve un resultado.
        Arugmentos: ret - resultado del establecimiento de la llamada.
        '''
        #Todas las ventanas de informacion se muestran en segundo plano para no bloquear la GUI.
        if ret == -2:
            self.app.thread(self.app.infoBox,"Usuario ocupado", "El usuario al que llama está ocupado.")
            self.app.enableButton("Conectar")
            self.app.disableButton("Espera")
            self.app.disableButton("Colgar")
        elif ret == -3:
            self.app.thread(self.app.infoBox,"Llamada rechazada", "El usuario indicado rechazó la llamada.")
            self.app.enableButton("Conectar")
            self.app.disableButton("Espera")
            self.app.disableButton("Colgar")
        elif ret == -1:
            self.app.thread(self.app.errorBox,"Error durante la llamada", "No ha podido establecerse la conexión con el usuario indicado.")
            self.app.enableButton("Conectar")
            self.app.disableButton("Espera")
            self.app.disableButton("Colgar")
        else:
            self.app.thread(self.app.infoBox,"Conectado", "Se ha conectado exitosamente al usuario objetivo.")
            self.app.disableButton("Conectar")
            self.app.enableButton("Espera")
            self.app.enableButton("Colgar")

    def list_handler(self):
        '''
        Nombre: list_handler
        Descripcion: Se ejecuta cuando el usuario seleccione un nick de la lista.
        '''
        #Cuando se pincha en la lista se usa ese nombre para llamar.
        inputs = self.app.getListBox("nicksList")
        if len(inputs) > 0:
            nick = inputs[0]
            self.app.setEntry("calleeNickInput", nick)

    def populate_list(self):
        '''
        Nombre: populate_list
        Descripcion: Funcion pensada para rellenar la lista de usuarios de forma asincrona.
        '''
        #Poblamos la lista de usuarios con los nombres
        users = self.discovery.list_users()
        if users == None:
            print("Error obteniendo listado de usuarios.")
            return

        self.app.updateListBox("nicksList", [e[0] for e in users if len(e) > 0], select=False)

#PROGRAMA PRINCIPAL

if __name__ == '__main__':

    #Crear objeto GUI
    vc = VideoClient("1280x720")

    # Lanza el bucle principal del GUI
    # El control ya NO vuelve de esta función, por lo que todas las
    # acciones deberán ser gestionadas desde callbacks y threads
    vc.start()
