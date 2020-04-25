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
from video import send_frame, decompress



class VideoClient(object):

    connection_loop = None
    command_loop = None
    nick = None
    listen_control_port = "10000"
    boolResetFrame = 1
    socket_video_send = None
    socket_video_rec = None
    num = 0

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
        self.app.setStopFunction(self.stop)
        self.app.setStartFunction(self.on_startup)

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

        self.app.setStatusbar("Conectado al server de descubrimiento.",field=0)
        # Entrada del nick del usuario a conectar
        print("Comenzando registro de usuario.")
        register_nick = self.app.textBox("Inicio", "Introduce tu nick de usuario.")
        password = self.app.textBox("Inicio", "Introduce tu contrasena.")

        control_port = self.app.integerBox("Inicio", "Introduce tu puerto de escucha para conexiones TCP.")
        video_port = self.app.integerBox("Inicio", "Introduce tu puerto para recibir video UDP.")

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
            self.app.errorBox("Error", "El puerto introducido es invalido. Debe estar en el rango 1024-65535")
            self.app.stop()
            return

        ip = socket.gethostbyname(socket.gethostname())

        ret = -1
        while ret == -1:
            if not register_nick or not password or not control_port or not video_port or not ip:
                self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Faltan datos.")
                self.app.stop()
                return
            print("Tratando de registrar a " + register_nick + " con clave " + password + " puerto:" + control_port + " ip:" + ip + " puerto de video: " + video_port)
            ret = register_user(register_nick,password, ip, control_port)
            if not ret:
                #Error
                self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Error del servidor de descubrimiento.")
                self.app.stop()
                return

            #Clave incorrecta
            if ret == -1:
                password = self.app.textBox("Contraseña incorrecta.", "La contraseña es incorrecta. Por favor, introduzcala de nuevo.")

        self.app.setLabel("loggeduser", "Sesion iniciada como: " + register_nick)
        self.app.infoBox("Registro correcto", "El registro se ha realizado correctamente.")
        self.listen_control_port = control_port

        #Hilos de recepcion
        self.connection_loop = threading.Thread(target=control_listen_loop, args = (self.listen_control_port,self.app))
        self.command_loop = threading.Thread(target=control_incoming_loop, args = (self.app,))
        self.connection_loop.start()
        self.command_loop.start()

        user_data = {"username":register_nick, "tcp_port":control_port, "udp_port":video_port}
        with open(user_filename, "w+") as file:
            json.dump(user_data,file, indent=4)

        #Iniciamos los sockets de video
        self.socket_video_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket_video_rec = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Función que captura el frame a mostrar en cada momento
    def capturaVideo(self):

        # Capturamos un frame de la cámara o del vídeo
        ret, frame = self.cap.read()
        frame = cv2.resize(frame, (640,480))

        # Código que envia el frame a la red
        status = call_status()
        #TODO el contador num podria empezar como atributo a 0 y cada vez que se reinicie llamada (mirando el call status), reiniciarlo.
        if(status[0] != None and status[0] != "HOLD1" and status[0] != "HOLD2"):

            if(self.boolResetFrame == 1):
                self.num = 0
                self.boolResetFrame = 0
                self.startTime = time.time()
                self.socket_video_rec.bind(('',int(get_video_port())))

            #EN LLAMADA. #TODO en el campo 1 de la statusbar poner info: DURACION; FPS... Una vez mas hace falta detectar reinicios en call_status.
            self.app.setStatusbar("En llamada con: " + get_connected_username() ,field=0)
            self.app.setStatusbar("Duracion: " + str(time.time() - self.startTime) ,field=1)

            #Enviamos el frame
            errorSend = send_frame(self.socket_video_send, (status[0],int(status[1])), frame, self.num, 50, "640x480", 40)
            if(errorSend == -1):
                print("Error sending message")
            self.num += 1

            #Leemos el frame que nos envian
            data, _ = self.socket_video_rec.recvfrom(1024)
            frame_rec = decompress(data)

            frame_peque = cv2.resize(frame, (320,240)) # ajustar tamaño de la imagen pequeña
            frame_compuesto = frame_rec
            frame_compuesto[0:frame_peque.shape[0], 0:frame_peque.shape[1]] = frame_peque
            frame = frame_compuesto

        elif status[0] == "HOLD1":
            self.app.setStatusbar("Llamada en espera por " + get_username() ,field=0)
        elif status[0] == "HOLD2":
            self.app.setStatusbar("Llamada en espera por " + get_connected_username() ,field=0)
        elif get_connected_username() != None:
            self.app.setStatusbar("Llamando a " + get_connected_username(),field=0)
        else:
            self.app.setStatusbar("Cliente listo para llamar.",field=0)
            if(self.boolResetFrame != 1):
                self.boolResetFrame = 0

        #Mostramos por la GUI ambas webcams o solo la nuestra si no hay ninguna llamada
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

    vc = VideoClient("640x520")

    # Se inicializa en on_startup() para poder mostrar ventanas de info

    # Lanza el bucle principal del GUI
    # El control ya NO vuelve de esta función, por lo que todas las
    # acciones deberán ser gestionadas desde callbacks y threads
    vc.start()
