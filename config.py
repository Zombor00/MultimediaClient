import json

#Parametros constantes del QoS
BUFFER_SIZE = 256 #Tamano maximo para el buffer.
BUFFER_THRESHOLD = 10 #Numero de frames que han tenido que llegar para que se reproduzcan frames
FIXED_DELAY_THRESHOLD = 0.25 #Milisegundos de margen que se permiten como mucho para el retardo fijo.
FPS_REFRESH = 5.0 #Cada cuanto se intenta reajustar los fps
QUALITY_REFRESH = 1.0 #Cada cuanto se intenta reajustar la calidad de compresion
RESOLUTION_REFRESH = 10.0 #Cada cuanto se intenta reajustar la resolucion del video

#Parametros control
call_timeout = 15 #Timeout para responder a la llamada
user_filename = "usuario.json" #Fichero de usuario

#Config server descubrimiento
server_ip = "vega.ii.uam.es"
server_port = 8000

#Cargamos el fichero
def read_config():
	try:
		with open("config.json", "r") as file:
        	config = json.load(file)
	except (FileNotFoundError, json.JSONDecodeError):
		return
	
	for key in list(config.keys()):
    	if key in globals():
    		globals()[key] = config[key]