'''
   video.py
   Modulo encargado del apartado criptográfico de securebox
   @author Alejandro Bravo, Miguel Gonzalez
   @version 1.0
   @date 23-04-2020
'''

import threading
import heapq
import time
import cv2
import numpy as np

class VideoBuffer():
    '''Buffer de video: Encapsula el estado y funcionalidades del buffer de video'''

    #Variables globales de estado del modulo
    buffer_lock = threading.Lock() #Cerrojo para el buffer en los 2 hilos (recepcion de la red y extraccion para reproducir)
    buffer_heap = [] #Buffer de video (lista de paquetes)
    buffer_num = 0 #Ultimo paquete que se extrajo del buffer. Esto evita que llegue uno posterior a uno ya emitido.
    timemax = -1 #Retardo fijo. No se reproduciran paquetes pasado este retardo fijo desde su emision.
    packets_lost = [0, 0, 0, 0] #4 contadores de paquetes uno para cada ajuste (calidad,FPS,resolucion,reportes salientes) posible.
    time_last_check_qual = -1 #Timestamp con la ultima vez que se intento actualizar la calidad
    time_last_check_fps = -1 #Timestamp con la ultima vez que se intentaron actualizar los FPS
    time_last_check_res = -1 #Timestamp con la ultima vez que se intento actualizar la resolucion
    buffer_block = True #Indicara al buffer si puede sacar frames o no. Solo lo levantaremos cuando este parcialmente lleno.

    #MEDIDAS PARA AJUSTAR QoS. Cada valor es una fraccion de frames. 
    # Por ejemplo, si desde la ultima comprobacion debieron llegar
    # 10 paquetes, y llegan 6, entonces ha habido una fraccion de 0.4 de perdidas.
    MEDIUM_LOST = 1/15 #Fraccion de frames perdida por segundo que se considera mediocre.
    WORST_LOST = 4/15 #Fraccion de frames perdida por segundo que se considera mala

    #Variables de V1
    last_timestamp = 0 #Marca de tiempo del ultimo reporte
    last_loss_per_second = 0 #Paquetes perdidos por segundo segun el ultimo reporte
    time_last_sent_report = -1 #Timestamp con la ultima vez que se envio reporte de errores
    report_lock = threading.Lock() #Cerrojo para manipular las variables de reportes de perdidas
    using_v1 = False #Indica si se esta usando la version 1, para enviar reportes de perdidas.
    control = None #Modulo de control

    config = None #Objeto de configuracion

    def __init__(self, config):
        '''
        Nombre: __init__
        Descripcion: Constructor que ajusta el objeto de configuracion
        '''
        self.config = config

    def send_frame(self, socket_video, status, frame, numOrden, quality ,resolution, fps):
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
        encimg = compress(frame, quality)
        header = str(numOrden) + "#" + str(time.time()) + "#" + resolution + "#" + str(fps) + "#"
        header = header.encode()
        message = header + encimg
        lengthTot = len(message)

        try:
            lengthSend = socket_video.sendto(message, status)
        except OSError:
            lengthSend = -1
            print("UDP Error: El frame no entra en el datagrama.")

        if(lengthSend != lengthTot):
            return -1
        return 0


    def receive_frame(self, socket_video_rec):
        '''
        Nombre: receive_frame
        Descripcion: Funcion que va recibiendo frames, descomprimiendolos e incluyendolos en un
                    heap.
        Argumentos: socket_video_rec: Socket UDP con el que se recibe el frame.
        Retorno:
            None
        '''
        #Inicializar las variables de control del modulo de video.
        self.buffer_num = -1
        self.timemax = -1
        self.packets_lost = [0, 0, 0, 0]
        self.time_last_check_qual = time.time()
        self.time_last_check_fps = time.time()
        self.time_last_check_res = time.time()
        self.time_last_sent_report = time.time()
        self.last_timestamp = time.time()

        #Vaciar el socket. Podrian quedar restos de llamadas previas, 
        #cuyos numeros de secuencia lian al contador de paquetes perdidos.
        socket_video_rec.setblocking(0)
        try:
            while socket_video_rec.recvfrom(65535):
                pass
        except OSError:
            #No queda nada que vaciar
            pass
        socket_video_rec.setblocking(1)

        while True:
            data, _ = socket_video_rec.recvfrom(65535)

            if(data == b'END_RECEPTION'):
                return

            with self.buffer_lock:
                video_length = len(self.buffer_heap)

            if(data != None and video_length < self.config.BUFFER_SIZE):
                header,decimg = decompress(data)
                timestamp = float(header[1])
                incoming_fps = int(header[3])

                #Calculo del retardo fijo maximo
                if(self.timemax == -1):
                    #Retardo de red
                    network_delay_estimate = time.time() - timestamp
                    #Retardo que tendra lugar a causa de la espera inicial del buffer
                    buffer_threshold_delay_estimate = self.config.BUFFER_THRESHOLD/incoming_fps
                    #Tiempo maximo de retardo que permitiremos
                    self.timemax = network_delay_estimate + buffer_threshold_delay_estimate + self.config.FIXED_DELAY_THRESHOLD

                #Eliminamos los elementos anteriores al ultimo extraido
                with self.buffer_lock:
                    if((self.buffer_num < int(header[0]))):
                        heapq.heappush(self.buffer_heap, (int(header[0]), header, decimg))
                    #Levantamos el buffer cuando haya un poco de cantidad
                    if(len(self.buffer_heap) > self.config.BUFFER_THRESHOLD):
                        self.buffer_block = False

    def pop_frame(self, quality, fps, resolution, packets_lost_total, min_fps=20, max_fps=40):
        '''
        Nombre: pop_frame
        Descripcion: Extrae un elemento del buffer. Cada elemento es una tripla que
                    contiene el numero de frame, el header y el frame. Ajusta
                    la calidad del video dependiendo de los frames perdidos.
                    heap.
        Argumentos: min_fps : Valor minimo de fps que el QoS puede ajustar.
                    max_fps : Valor maximo de fps que el QoS puede ajustar.

                    Datos que actualiza la funcion (deben pasarse por referencia, envueltos en una lista):
                    quality: Calidad con la que se están comprimiendo los frames
                    fps: Frames que se envian al segundos
                    resolution: Resolucion a la que se captura la imagen
                    self.packets_lost_total: Numero total de paquetes perdidos esta llamada
        Retorno:
            - Si hay elementos: se devuelven 3 elementos. El primero es el numero
            de frame, el segundo elemento es el header y el último el propio frame descomprimido.
            - Si el buffer esta bloqueado se devuelven 3 elementos: -1, una lista vacia
            y un numpy array vacio.
        '''
        #El buffer debe estar desbloqueado, es decir, deben haber llegado suficientes elementos para poder ir extrayendo.
        if(not self.buffer_block):
            with self.buffer_lock:

                #Almacenamos el instante actual
                time_epoch = time.time()

                #Guardamos los fps a los que se envio el frame que vamos a leer
                #buffer[0] -> paquete actual
                #campo 1 -> Header
                #campo 3 del header -> FPS
                fps_entrante = int(self.buffer_heap[0][1][3])
                if fps_entrante <= 0:
                    fps_entrante = 1

                #Si el paquete que toca sacar esta muy retrasado, lo descartamos y sacamos otro
                #buffer[0] -> paquete que toca sacar
                #campo 1 -> Header
                #campo 1 del header -> timestamp
                #Si solo queda un paquete no lo hacemos dado que no hay mas remedio que usar ese
                while len(self.buffer_heap) > 1 and (time_epoch - float(self.buffer_heap[0][1][1]) > self.timemax):
                    heapq.heappop(self.buffer_heap) #Extraccion del paquete descartado

                #Añadimos el numero de paquetes perdidos
                if(self.buffer_num != -1 ):
                    #Paquetes perdidos desde el ultimo que se saco (self.buffer_num)
                    packets_lost_now = self.buffer_heap[0][0] - self.buffer_num -1
                    if(packets_lost_now < 0):
                        packets_lost_now = 0
                    #Se agregan a los 3 contadores (uno para cada parametro de calidad)
                    self.packets_lost[0] += packets_lost_now
                    self.packets_lost[1] += packets_lost_now
                    self.packets_lost[2] += packets_lost_now
                    self.packets_lost[3] += packets_lost_now
                    #Se agregan al conteo total
                    packets_lost_total[0] += packets_lost_now

                #V1: Calculamos fraccion de perdidas segun reporte
                report_fraction = self.last_loss_per_second / fps[0]
                weigth = self.config.REPORT_WEIGHT

                #Ajustamos la calidad de compresión cada QUALITY_REFRESH
                if(time_epoch - self.time_last_check_qual > self.config.QUALITY_REFRESH):

                    quality_fraction = self.packets_lost[0]/(self.config.QUALITY_REFRESH * fps_entrante)
                    if(report_fraction != 0):
                        quality_fraction = quality_fraction * (1-weigth) + report_fraction * weigth

                    if(quality_fraction < self.MEDIUM_LOST):
                        quality[0] = 75
                    elif(quality_fraction < self.WORST_LOST):
                        quality[0] = 50
                    else:
                        quality[0] = 25

                    self.packets_lost[0] = 0
                    self.time_last_check_qual = time_epoch

                #Ajustamos los fps cada FPS_REFRESH
                if(time_epoch - self.time_last_check_fps > self.config.FPS_REFRESH):

                    fps_fraction = self.packets_lost[1]/(self.config.FPS_REFRESH * fps_entrante)
                    if(report_fraction != 0):
                        fps_fraction = fps_fraction * (1-weigth) + report_fraction * weigth

                    if(fps_fraction < self.MEDIUM_LOST):
                        fps[0] = max_fps
                    elif(fps_fraction < self.WORST_LOST):
                        fps[0] = (max_fps + min_fps) // 2
                    else:
                        fps[0] = min_fps

                    self.packets_lost[1] = 0
                    self.time_last_check_fps = time_epoch

                #Ajustamos la resolucion cada RESOLUTION_REFRESH
                if(time_epoch - self.time_last_check_res > self.config.RESOLUTION_REFRESH):

                    resolution_fraction = self.packets_lost[2]/(self.config.RESOLUTION_REFRESH * fps_entrante)
                    if(report_fraction != 0):
                        resolution_fraction = resolution_fraction * (1-weigth) + report_fraction * weigth

                    if(resolution_fraction < self.MEDIUM_LOST):
                        resolution[0] = "640x480"
                    elif(resolution_fraction < self.WORST_LOST):
                        resolution[0] = "320x240"
                    else:
                        resolution[0] = "160x120"

                    self.packets_lost[2] = 0
                    self.time_last_check_res = time_epoch

                #Mandar reportes de perdidas a los que usen V1
                if(self.using_v1):
                    if(time_epoch - self.time_last_sent_report > self.config.REPORT_REFRESH):
                        self.control.send_loss_report(self.packets_lost[3])
                        self.packets_lost[3] = 0
                        self.time_last_sent_report = time_epoch

                #Actualizamos el buffer num al numero del header del primer elemento
                self.buffer_num = self.buffer_heap[0][0]

                #Evitamos vaciado completo en caso de que no se este recibiendo a suficiente ritmo
                if len(self.buffer_heap) == 1:
                    return self.buffer_heap[0]

                return heapq.heappop(self.buffer_heap)

        else:
            return -1, list(), np.array([])

    def set_loss_report(self, lost, timestamp):
        '''
        Nombre: set_lost_report
        Descripcion: Ajusta los datos de perdidas del otro extremo.
        Argumentos:
            lost: paquetes perdidos segun el reporte
            timestamp: Marca de tiempo del reporte
        '''
        with self.report_lock:
            self.last_loss_per_second = lost/(time.time()-self.last_timestamp)
            self.last_timestamp = timestamp

    def set_control(self, control):
        '''
        Nombre: set_control
        Descripcion: Ajusta el modulo de control.
        Argumentos:
            control: Objeto con modulo de control.
        '''
        self.control = control

    def set_using_v1(self):
        '''
        Nombre: set_using_v1
        Descripcion: Indica al modulo de video que el otro cliente usa v1
        '''
        self.using_v1 = True

    def empty_buffer(self):
        '''
        Nombre: empty_buffer
        Descripcion: Vacia el buffer.
        '''
        self.buffer_heap = []
        self.buffer_block = True
        self.last_loss_per_second = 0
        self.using_v1 = False

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
