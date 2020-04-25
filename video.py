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

