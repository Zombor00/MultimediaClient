'''
   video.py
   Modulo encargado del apartado criptográfico de securebox
   @author Alejandro Bravo, Miguel Gonzalez
   @version 1.0
   @date 23-04-2020
'''

import socket
import time
import cv2
import numpy as np
import threading
import heapq

#Variables globales de estado del modulo
buffer_lock = threading.Lock() #Cerrojo para el buffer en los 2 hilos (recepcion de la red y extraccion para reproducir)
buffer_num = 0 #Ultimo paquete que se extrajo del buffer. Esto evita que llegue uno posterior a uno ya emitido.
timemax = -1 #Retardo fijo. No se reproduciran paquetes pasado este retardo fijo desde su emision.
packets_lost = [0,0,0] #3 contadores de paquetes uno para cada ajuste (calidad,FPS,resolucion) posible.
time_last_check_qual = -1 #Timestamp con la ultima vez que se intento actualizar la calidad
time_last_check_fps = -1 #Timestamp con la ultima vez que se intentaron actualizar los FPS
time_last_check_res = -1 #Timestamp con la ultima vez que se intento actualizar la resolucion

#Parametros constantes del QoS
BUFFER_SIZE = 256 #Tamano maximo para el buffer.
BUFFER_THRESHOLD = 10 #Numero de frames que han tenido que llegar para que se reproduzcan frames
FIXED_DELAY_THRESHOLD = 0.25 #Milisegundos de margen que se permiten como mucho para el retardo fijo.
FPS_REFRESH = 5.0 #Cada cuanto se intenta reajustar los fps
QUALITY_REFRESH = 1.0 #Cada cuanto se intenta reajustar la calidad de compresion
RESOLUTION_REFRESH = 10.0 #Cada cuanto se intenta reajustar la resolucion del video

#MEDIDAS PARA AJUSTAR QoS. Cada valor es una fraccion de frames. 
# Por ejemplo, si desde la ultima comprobacion debieron llegar 
# 10 paquetes, y llegan 6, entonces ha habido una fraccion de 0.4 de perdidas.
MEDIUM_LOST = 1/15 #Fraccion de frames perdida por segundo que se considera mediocre.
WORST_LOST = 4/15 #Fraccion de frames perdida por segundo que se considera mala

def send_frame(socket_video,status,frame,numOrden, quality ,resolution,fps):
    '''
    Nombre: send_frame
    Descripcion: Envia un frame comprimido a la ip/puerto indicados.
    Argumentos: socket_video: Socket UDP con el que se envia el frame.
                status: Contiene el ip y el puerto al que se envia el frame.
                frame: Frame a enviar.
                numOrden: Número del frame que se envía.
                quality: Calidad a la que se comprime.
                resolution: Resolucion del frame.
                fps: Numero de frames que se envian por segundo.
    Retorno:
        En caso de que no haya errores devuelve 0
        En caso de error devuelve -1.
    '''
    encimg = compress(frame,quality)
    header = str(numOrden) + "#" + str(time.time()) + "#" + resolution + "#" + str(fps) + "#"
    header = header.encode()
    message = header + encimg
    lengthTot = len(message)

    try:
        lengthSend = socket_video.sendto(message,status)
    except:
        lengthSend = -1
        print("UDP Error: El frame no entra en el datagrama.")

    if(lengthSend != lengthTot):
        return -1
    return 0


def receive_frame(socket_video_rec,buffer_video,buffer_block):
    '''
    Nombre: receive_frame
    Descripcion: Funcion que va recibiendo frames, descomprimiendolos e incluyendolos en un
                heap.
    Argumentos: socket_video_rec: Socket UDP con el que se recibe el frame.
                buffer_video: Heap que guarda los frames.
                buffer_block: Semáforo para acceder al heap.
    Retorno:
        None
    '''
    global buffer_num, packets_lost, time_last_check_qual, time_last_check_fps, timemax, time_last_check_res

    #Inicializar las variables de control del modulo de video.
    buffer_num = -1
    timemax = -1
    packets_lost = [0,0,0]
    time_last_check_qual = time.time()
    time_last_check_fps = time.time()
    time_last_check_res = time.time()

    #Vaciar el socket. Podrian quedar restos de llamadas previas, 
    #cuyos numeros de secuencia lian al contador de paquetes perdidos.
    socket_video_rec.setblocking(0)
    try:
        while socket_video_rec.recvfrom(65535):
            pass
    except:
        #No queda nada que vaciar
        pass
    socket_video_rec.setblocking(1)

    while True:
        data, _ = socket_video_rec.recvfrom(65535)

        if(data == b'END_RECEPTION'):
            return

        with buffer_lock:
            video_length = len(buffer_video)

        if(data != None and video_length < BUFFER_SIZE):
            header,decimg = decompress(data)
            timestamp = float(header[1])
            incoming_fps = int(header[3])

            #Calculo del retardo fijo maximo
            if(timemax == -1):
                #Retardo de red
                network_delay_estimate = time.time() - timestamp
                #Retardo que tendra lugar a causa de la espera inicial del buffer
                buffer_threshold_delay_estimate = BUFFER_THRESHOLD/incoming_fps
                #Tiempo maximo de retardo que permitiremos
                timemax = network_delay_estimate + buffer_threshold_delay_estimate + FIXED_DELAY_THRESHOLD

            #Eliminamos los elementos anteriores al ultimo extraido
            with buffer_lock:
                if((buffer_num < int(header[0]))):
                    heapq.heappush(buffer_video,(int(header[0]),header,decimg))
                #Levantamos el buffer cuando haya un poco de cantidad
                if(len(buffer_video) > BUFFER_THRESHOLD):
                    buffer_block[0] = False

def pop_frame(buffer, block, quality, fps, resolution, packets_lost_total):
    '''
    Nombre: pop_frame
    Descripcion: Extrae un elemento del buffer. Cada elemento es una tripla que
                 contiene el numero de frame, el header y el frame. Ajusta
                 la calidad del video dependiendo de los frames perdidos.
                heap.
    Argumentos: buffer: Heap del que se extrae la tripla.
                block: Indica si está bloqueada la extraccion de frames.

                Datos que actualiza la funcion (deben pasarse por referencia, envueltos en una lista):
                quality: Calidad con la que se están comprimiendo los frames
                fps: Frames que se envian al segundos
                resolution: Resolucion a la que se captura la imagen
                packets_lost_total: Numero total de paquetes perdidos esta llamada
    Retorno:
        - Si hay elementos: se devuelven 3 elementos. El primero es el numero
        de frame, el segundo elemento es el header y el último el propio frame descomprimido.
        - Si el buffer esta bloqueado se devuelven 3 elementos: -1, una lista vacia
        y un numpy array vacio.
    '''
    global buffer_num, packets_lost, time_last_check_qual, time_last_check_fps, time_last_check_res
    #El buffer debe estar desbloqueado, es decir, deben haber llegado suficientes elementos para poder ir extrayendo.
    if(not block[0]):
        with buffer_lock:

            #Almacenamos el instante actual
            time_epoch = time.time()

            #Guardamos los fps a los que se envio el frame que vamos a leer
            #buffer[0] -> paquete actual
            #campo 1 -> Header
            #campo 3 del header -> FPS
            fps_entrante = int(buffer[0][1][3])

            #Si el paquete que toca sacar esta muy retrasado, lo descartamos y sacamos otro
            #buffer[0] -> paquete que toca sacar
            #campo 1 -> Header
            #campo 1 del header -> timestamp
            #Si solo queda un paquete no lo hacemos dado que no hay mas remedio que usar ese
            while len(buffer) > 1 and (time_epoch - float(buffer[0][1][1]) > timemax):
                heapq.heappop(buffer) #Extraccion del paquete descartado

            #Añadimos el numero de paquetes perdidos
            if(buffer_num != -1 ):
                #Paquetes perdidos desde el ultimo que se saco (buffer_num)
                packets_lost_now = buffer[0][0] - buffer_num -1
                if(packets_lost_now < 0):
                    packets_lost_now = 0
                #Se agregan a los 3 contadores (uno para cada parametro de calidad)
                packets_lost[0] += packets_lost_now
                packets_lost[1] += packets_lost_now
                packets_lost[2] += packets_lost_now
                #Se agregan al conteo total
                packets_lost_total[0] += packets_lost_now

            #Ajustamos la calidad de compresión cada QUALITY_REFRESH
            if(time_epoch - time_last_check_qual > QUALITY_REFRESH):
                if(packets_lost[0] < MEDIUM_LOST * QUALITY_REFRESH * fps_entrante):
                    quality[0] = 75
                elif(packets_lost[0] < WORST_LOST * QUALITY_REFRESH * fps_entrante):
                    quality[0] = 50
                else:
                    quality[0] = 25
                packets_lost[0] = 0
                time_last_check_qual = time_epoch

            #Ajustamos los fps cada FPS_REFRESH
            if(time_epoch - time_last_check_fps > FPS_REFRESH):
                if(packets_lost[1] < MEDIUM_LOST * FPS_REFRESH * fps_entrante):
                    fps[0] = 40
                elif(packets_lost[1] < WORST_LOST * FPS_REFRESH * fps_entrante):
                    fps[0] = 30
                else:
                    fps[0] = 20
                packets_lost[1] = 0
                time_last_check_fps = time_epoch

            #Ajustamos la resolucion cada RESOLUTION_REFRESH
            if(time_epoch - time_last_check_res > RESOLUTION_REFRESH):
                if(packets_lost[2] < MEDIUM_LOST * RESOLUTION_REFRESH * fps_entrante):
                    resolution[0] = "640x480"
                elif(packets_lost[2] < WORST_LOST * RESOLUTION_REFRESH * fps_entrante):
                    resolution[0] = "320x240"
                else:
                    resolution[0] = "160x120"
                packets_lost[2] = 0

                time_last_check_res = time_epoch

            #Actualizamos el buffer num al numero del header del primer elemento
            buffer_num = buffer[0][0]

            #Evitamos vaciado completo en caso de que no se este recibiendo a suficiente ritmo
            if len(buffer) == 1:
                return buffer[0]

            return heapq.heappop(buffer)

    else:
        return -1, list(), np.array([])


def compress(frame,quality):
    '''
    Nombre: compress
    Descripcion: Comprime un frame.
    Argumentos: frame: Frame que se va a comprimir.
                quality: String que indica la calidad a la que se va a comprimir.
    Retorno:
        - Si no hay errores se devuelve el frame comprimido.
        - Si hay error al comprimir se devuelve None.
    '''
    # Compresión JPG al 50% de resolución (se puede variar)
    encode_param = [cv2.IMWRITE_JPEG_QUALITY,quality]
    result,encimg = cv2.imencode('.jpg',frame,encode_param)

    if(result == False):
        print('Error al codificar imagen')
        return None

    return encimg.tostring()


def decompress(encimg):
    '''
    Nombre: decompress
    Descripcion: Descomprime un frame.
    Argumentos: frame: Frame que se va a descomprimir.
    Retorno:
        - Si no hay errores se devuelve el header del mensaje y el frame descomprimido.
        - Si hay error al comprimir se devuelve None.
    '''
    count = 0
    ENCODED_HASHTAG = 35 #Codigo de la almohadilla (Si no no funciona)
    for i in range(0, len(encimg)):
        if encimg[i] == ENCODED_HASHTAG:
            count +=1
            if count == 4:
                break

    if(i == len(encimg)):
        print("Error en el datagrama.")
        return None

    header = encimg[:i]
    content = encimg[i+1:]
    header = header.decode()
    header = header.split("#")
    decimg = cv2.imdecode(np.frombuffer(content,np.uint8), 1)

    return header, decimg
