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
    header = bytes(header,"ascii")
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
    decimg = cv2.imdecode(np.frombuffer(encimg,np.uint8), 1)

    # Conversión de formato para su uso en el GUI
    #cv2_im = cv2.cvtColor(decimg,cv2.COLOR_BGR2RGB)
    #img_tk = ImageTk.PhotoImage(Image.fromarray(cv2_im))

    #return img_tk
