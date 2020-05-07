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

buffer_lock = threading.Lock()
buffer_num = 0

def send_frame(socket_video,status,frame,numOrden,quality,resolution,fps):
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
    global buffer_num
    timemax = -1
    buffer_num = -65535
    while True:
        data, _ = socket_video_rec.recvfrom(65535)

        if(data == b'END_RECEPTION'):
            return

        with buffer_lock:
            video_length = len(buffer_video)

        if(data != None and video_length < 1024):
            header,decimg = decompress(data)
            timestamp = float(header[1])

            if(timemax == -1):
                timemax = time.time() - timestamp + 0.04

            #Eliminamos los elementos anteriores al ultimo extraido
            with buffer_lock:
                if((buffer_num < int(header[0])) and (time.time() - timestamp) < timemax):
                    heapq.heappush(buffer_video,(int(header[0]),header,decimg))
                #TODO Evitar que se haga esta comparación todo el rato
                if(len(buffer_video) > 10):
                    buffer_block[0] = False

def pop_frame(buffer,block):
    '''
    Nombre: pop_frame
    Descripcion: Extrae un elemento del buffer. Cada elemento es una tripla que
                 contiene el numero de frame, el header y el frame.
                heap.
    Argumentos: buffer: Heap del que se extrae la tripla.
                block: Indica si está bloqueada la extraccion de frames.
    Retorno:
        - Si hay elementos: se devuelven 3 elementos. El primero es el numero
        de frame, el segundo elemento es el header y el último el propio frame descomprimido.
        - Si el buffer esta bloqueado se devuelven 3 elementos: -1, una lista vacia
        y un numpy array vacio.
    '''
    global buffer_num
    if(not block[0]):
        if(len(buffer) == 1):
            with buffer_lock:
                return buffer[0]
        else:
            with buffer_lock:
                #Actualizamos el buffer num al numero del header del primer elemento
                buffer_num = buffer[0][0]
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
