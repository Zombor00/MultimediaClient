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
    encimg = compress(frame,quality)
    header = str(numOrden) + "#" + str(time.time()) + "#" + resolution + "#" + str(fps) + "#"
    header = header.encode()
    message = header + encimg
    lengthTot = len(message)

    lengthSend = socket_video.sendto(message,status)
    if(lengthSend != lengthTot):
        return -1
    return 0

def receive_frame(socket_video_rec,buffer_video,buffer_block):
    global buffer_num
    buffer_num = -65535
    while True:
        data, _ = socket_video_rec.recvfrom(65535)

        if(data == b"END_RECEPTION"):
            return

        with buffer_lock:
            video_length = len(buffer_video)

        if(data != None and video_length < 1024):
            header,decimg = decompress(data)
            #Eliminamos los elementos anteriores al ultimo extraido

            with buffer_lock:
                if(buffer_num < int(header[0])):
                    heapq.heappush(buffer_video,(int(header[0]),decimg))
                #TODO Evitar que se haga esta comparación todo el rato
                if(len(buffer_video) > 10):
                    buffer_block[0] = False

def pop_frame(buffer,block):
    global buffer_num
    if(not block[0]):
        if(len(buffer) == 1):
            with buffer_lock:
                return buffer[0][1]
        else:
            with buffer_lock:
                #Actualizamos el buffer num al numero del header del primer elemento
                buffer_num = buffer[0][0]
                return heapq.heappop(buffer)[1]

    else:
        return np.array([])

def compress(frame,quality):
    # Compresión JPG al 50% de resolución (se puede variar)
    encode_param = [cv2.IMWRITE_JPEG_QUALITY,quality]
    result,encimg = cv2.imencode('.jpg',frame,encode_param)

    if result == False: print('Error al codificar imagen')

    return encimg.tostring()

def decompress(encimg):
    # Descompresión de los datos, una vez recibidos
    # DEVUELVE LISTA CON CABECERAS (COMO STRING) Y LA IMAGEN.
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
