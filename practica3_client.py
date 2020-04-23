# import the library
from appJar import gui
from PIL import Image, ImageTk
import numpy as np
import cv2
from discovery import server_init, server_quit, register_user, query_user
import threading
from control import control_incoming_loop, control_listen_loop,control_listen_stop,control_incoming_stop, user_filename
import socket
import json



class VideoClient(object):

	connection_loop = None
	command_loop = None
	nick = None
	listen_control_port = "10000"
	def __init__(self, window_size):
		
		# Creamos una variable que contenga el GUI principal
		self.app = gui("Redes2 - P2P", window_size)
		self.app.setGuiPadding(10,10)

		# Preparación del interfaz
		self.app.addLabel("title", "Cliente Multimedia P2P - Redes2 ")
		self.app.addImage("video", "imgs/webcam.gif")

		# Registramos la función de captura de video
		# Esta misma función también sirve para enviar un vídeo
		self.cap = cv2.VideoCapture(0)
		self.app.setPollTime(20)
		self.app.registerEvent(self.capturaVideo)

		# Añadir los botones
		self.app.addButtons(["Conectar", "Colgar", "Salir"], self.buttonsCallback)
		
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

		# Entrada del nick del usuario a conectar    
		print("Comenzando registro de usuario.")
		register_nick = self.app.textBox("Inicio", "Introduce tu nick de usuario.")
		password = self.app.textBox("Inicio", "Introduce tu contrasena.")

		control_port = str(self.app.integerBox("Inicio", "Introduce tu puerto de escucha para conexiones TCP."))
		video_port = str(self.app.integerBox("Inicio", "Introduce tu puerto para recibir video UDP."))
		ip = socket.gethostbyname(socket.gethostname())

		if not register_nick or not password or not control_port or not video_port or not ip:
			self.app.errorBox("Error", "No se ha podido realizar el registro correctamente. Faltan datos.")
			self.app.stop()
			return

		ret = -1
		while ret == -1:
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


		self.app.infoBox("Registro correcto", "El registro se ha realizado correctamente.")
		self.listen_control_port = control_port
		
		#Hilos de recepcion	
		self.connection_loop = threading.Thread(target=control_listen_loop, args = (self.listen_control_port,))
		self.command_loop = threading.Thread(target=control_incoming_loop)
		self.connection_loop.start()
		self.command_loop.start()

		user_data = {"username":register_nick, "tcp_port":control_port, "udp_port":video_port}
		with open(user_filename, "w+") as file:
			json.dump(user_data,file, indent=4)


	# Función que captura el frame a mostrar en cada momento
	def capturaVideo(self):
		
		# Capturamos un frame de la cámara o del vídeo
		ret, frame = self.cap.read()
		frame = cv2.resize(frame, (640,480))
		cv2_im = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
		img_tk = ImageTk.PhotoImage(Image.fromarray(cv2_im))		    

		# Lo mostramos en el GUI
		self.app.setImageData("video", img_tk, fmt = 'PhotoImage')

		# Aquí tendría que el código que envia el frame a la red
		# ...

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
	    	# Salimos de la aplicación
	        self.app.stop()
	    elif button == "Conectar":
	        # Entrada del nick del usuario a conectar    
	        nick = self.app.textBox("Conexión", 
	        	"Introduce el nick del usuario a buscar")        

if __name__ == '__main__':

	vc = VideoClient("640x520")

	# Se inicializa en on_startup() para poder mostrar ventanas de info

	# Lanza el bucle principal del GUI
	# El control ya NO vuelve de esta función, por lo que todas las
	# acciones deberán ser gestionadas desde callbacks y threads
	vc.start()