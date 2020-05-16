'''
   config.py
   Modulo encargado del parseo de valores de configuracion.
   @author Alejandro Bravo, Miguel Gonzalez
   @version 1.0
   @date 16-05-2020
'''

import json

class config_parser():

    # Valores por defecto

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

    #Nombres de las variables que se pueden ajustar
    can_set = ["BUFFER_SIZE","BUFFER_THRESHOLD","FIXED_DELAY_THRESHOLD", "FPS_REFRESH", "QUALITY_REFRESH",
    "RESOLUTION_REFRESH", "call_timeout", "user_filename", "server_ip", "server_port"]

    #Cargamos el fichero
    def __init__(self):
        '''
        Nombre: read_config
        Descripcion: Lee el fichero de configuracion e inicia los valores correspondientes
        En caso de error o parametro faltante, se pondran los valores por defecto.
        '''	  
        try:
            with open("config.json", "r") as file:
                config = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            print("Error leyendo fichero de configuracion parametros.")
            return
        
        for key in config:
            if key in self.can_set:
                setattr(self, key, config[key])
        
        print("CONFIG: Ajustados los parametros: " + str([k for k in config if k in self.can_set]))
        missing = [k for k in self.can_set if k not in config]
        if len(missing)>0:
            print("CONFIG: Se han ajustado valores por defecto para los parametros faltantes: " + str(missing))