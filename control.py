'''
    control.py
    Modulo que se encarga de emitir las conexiones de control.
    Incluye la funcion de escucha de conexiones de control.
    @author Miguel Gonzalez, Alejandro Bravo.
    @version 1.0
    @date 22-04-2020

    DESCRIPCION GENERAL DEL MODULO
    El modulo hace uso de semaforos en sus funciones. Por ello es importante hacer las cosas en orden.

    1. Preparar hilos de gestion de conexiones y de gestion de comandos con las funciones de bucle provistas.
    2. Si se desea llamar, se usa connect_to(username) exclusivamente (hay otras funciones auxiliares pero por si solas no ajustan los semaforos)
    3. Si se desea poner en espera o quitar, se usa set_on_hold()
    4. Si se desea conocer si esta en llamada, y los parametros relevantes se usa call_status()
    5. Los bucles gestionan las conexiones y comandos entrantes por si solos, de manera sincronizada.
    6. Si se desea terminar la conexion, hay que hacer call_end() y control_disconnect().
    7. Para detener los bucles se usan las funciones de stop.
'''

import socket
import time
import threading
import json

class Control():
    '''Clase de control: Objeto que encapsula el estado y la funcionalidad del modulo de control'''

    # Parametros
    socket_timeout = 2 #Timeout para receive en casos criticos.

    # ESTADO ACTUAL

    control_socket = None #Socket de control.
    connected_to = None #Nombre del usuario al que esta conectado.
    on_call_with = [None, None] #IP y puerto (como cadena) para transferencia de video. Si alguno es None, no esta en llamada.
    on_hold = False #Indica si se ha puesto la llamada en espera
    call_held = False #Indica si la otra parte ha puesto la llamada en espera.
    listen_end = False #Indica al hilo que escucha que debe parar.
    incoming_end = False #Indica al hilo que responde comandos entrantes que debe parar.
    connection_barrier = threading.Semaphore(0) #Barrera que impide el paso al hilo que responde comandos si no hay conexiones activas.
    global_lock = threading.Lock() #Cerrojo para las variables globales.
    tcp_port = 0 #Puerto de control para poder cerrarlo.
    udp_port = None #Puerto de entrada de video
    username = None #Nombre de usuario propio
    discovery = None #Objeto de descubrimiento
    call_timeout = 15 #Timeout para responder a la llamada
    user_filename = "usuario.json" #Fichero de usuario
    video_buffer = None #Buffer del modulo de video

    def __init__(self, discovery, call_timeout, user_filename, video_buffer):
        '''
            Nombre: __init__
            Descripcion: Inicializa los parametros deseados.
            Argumentos: discovery: modulo de descubrimiento.
                        call_timeout: Segundos de espera si el otro no coge la llamada
                        user_filename: Nombre del fichero de configuracion de usuario
                        video_buffer: Buffer del modulo de video.
        '''
        self.discovery = discovery
        self.call_timeout = call_timeout
        self.user_filename = user_filename
        self.video_buffer = video_buffer

    # INFORMACION
    def get_username(self):
        '''
            Nombre: get_username
            Descripcion: Obtiene el nombre de usuario propio.
            Argumentos:
            Retorno:
                Nombre de usuario
        '''
        data = None
        if not self.username:
            try:
                with open(self.user_filename, "r") as file:
                    data = json.load(file)
            except (FileNotFoundError, json.JSONDecodeError):
                print("Error abriendo fichero de usuario.")
                self.control_disconnect() #Desconectamos del usuario actual.
                return "Error"
            self.username = data["username"]
        return self.username

    def get_video_port(self):
        '''
            Nombre: get_video_port
            Descripcion: Obtiene el puerto en el que se recibe el video.
            Argumentos:
            Retorno:
                Puerto en el que se recibe el video.
        '''
        data = None
        if not self.udp_port:
            try:
                with open(self.user_filename, "r") as file:
                    data = json.load(file)
            except (FileNotFoundError, json.JSONDecodeError):
                print("Error abriendo fichero de usuario.")
                self.control_disconnect() #Desconectamos del usuario actual.
                return "Error"
            self.udp_port = data["udp_port"]
        return self.udp_port

    def get_connected_username(self):
        '''
            Nombre: get_connected_username
            Descripcion: Obtiene el nombre del usuario con el que esta conectado.
            Argumentos:
            Retorno:
                Usuario con el que esta conectado o None.
        '''
        with self.global_lock:
            return self.connected_to


    # CONTROL SALIENTE

    def connect_to(self, username):
        '''
            Nombre: connect_to
            Descripcion: Inicializa la conexion de control con un usuario y lo llama.
            Argumentos: username: Nombre de usuario.
            Retorno:
                En caso de que se haya aceptado, devuelve el puerto donde ha de enviarse el video, como entero.
                En caso de error devuelve -1.
                En caso de que el usuario destino este en llamada, devuelve -2.
                En caso de que el usuario destino rechace la llamada, devuelve -3.
                Siempre imprime por pantalla el resultado.
        '''

        with self.global_lock:
            connected_to_read = self.connected_to

        if connected_to_read is not None:
            print("Error conectandose al usuario indicado. Ya esta conectado al usuario: " + connected_to_read)
            return -1

        #Obtenemos la IP y el puerto.
        ret = self.discovery.query_user(username)
        if ret is None:
            print("Error conectandose al usuario indicado. El servidor reporta que no existe.")
            return -1
        if self.connect_to_addr(ret[0], ret[1]) == -1:
            return -1

        #Ajuste de parametros
        with self.global_lock:
            self.connected_to = username
            self.on_hold = False #Reinicia la espera de la llamada.
            self.call_held = False
            self.on_call_with = [ret[0], None] #Vamos ajustando la IP de video
            if "V1" in ret[2]:
                self.video_buffer.set_using_v1()
        return self.call(int(self.get_video_port())) #Se efectua la llamada

    def connect_to_addr(self, ip, port):
        '''
            Nombre: connect_to_addr
            Descripcion: Inicializa la conexion de control con un usuario.
            Argumentos: ip: Ip a la que conectarse.
                        port: puerto al que conectarse.
            Retorno:
                0 si todo ha ido correctamente, -1 en caso de error.
        '''
        with self.global_lock:
            #Zona protegida porque tocamos el socket global.
            #Ademas esto se ejecuta puntualmente (cuando el usuario llama), asi que no
            #interfiere en exceso con los hilos en bucle.

            if self.control_socket is not None:
                print("Ya hay una conexion de control establecida. Debe cerrarse primero.")
                return -1

            self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if self.control_socket is None:
                return -1

            print("Conectandose al usuario con ip " + ip + " y puerto " + port)
            try:
                self.control_socket.settimeout(self.socket_timeout)
                self.control_socket.connect((ip, int(port)))
                self.control_socket.settimeout(None)
            except socket.timeout:
                print ("No ha sido posible conectarse al usuario. El usuario no ha aceptado la conexion en el tiempo establecido.")
                self.control_socket.close()
                self.control_socket = None
                return -1

        return 0

    def control_disconnect(self):
        '''
            Nombre: control_disconnect
            Descripcion: Finaliza la conexion de control saliente abierta previamente.
            Argumentos:
            Retorno:
                0 si todo ha ido correctamente, -1 en caso de error.
        '''

        with self.global_lock:

        #Zona protegida porque altera el estado.
            if self.control_socket == None:
                #Reseteamos parametros
                self.on_call_with = [None, None]
                self.control_socket = None
                self.connected_to = None
                self.on_hold = False
                return -1

            self.control_socket.close()
            #Reinicio de variables
            self.on_call_with = [None, None]
            self.control_socket = None
            self.connected_to = None
            self.on_hold = False
        self.connection_barrier.acquire() #Bajamos el semaforo de conexion
        return 0

    def call(self, dstport):
        '''
            Nombre: call
            Descripcion: Llama a un usuario por la conexion de control ya abierta.
            Argumentos: dstport: Puerto por el que se van a aceptar las conexiones, como entero.
            Retorno:
                En caso de que se haya aceptado, devuelve el puerto donde ha de enviarse el video, como entero.
                En caso de error devuelve -1.
                En caso de que el usuario destino este en llamada, devuelve -2.
                En caso de que el usuario destino rechace la llamada, devuelve -3.
                Siempre imprime por pantalla el resultado.
        '''

        with self.global_lock:
            #Zona protegida por operar con el socket
            if self.control_socket == None or self.connected_to == None:
                print ("Error llamando: no se esta conectado a ningun usuario.")
                return None
            mensaje = "CALLING " + self.get_username() + " " + str(dstport)
            self.control_socket.send(mensaje.encode())

        with self.global_lock:
            #Por si cambia la conexion, guardamos el socket actual. Esto es para no bloquear el lock durante receive que puede tardar.
            control_socket_read = self.control_socket

        try:
            #try except por si nos han cerrado el socket, y para el timeout.
            control_socket_read.settimeout(self.call_timeout)
            result = control_socket_read.recv(1024)
            control_socket_read.settimeout(None)
        except socket.timeout:
            print("Error iniciando llamada: el otro lado no ha respondido. Cerrando conexion...")
            self.connection_barrier.release() #Para que pueda hacerse la desconexion
            self.control_disconnect()
            return -1

        self.connection_barrier.release() #Subimos el semaforo de conexion, ya solo leera el otro hilo

        if not result:
            #El otro ha cerrado la conexion. El hilo de procesado de comandos cerrara nuestro lado. Salimos
            print("Error iniciando llamada: el otro extremo ha cerrado la conexion.")
            self.control_disconnect()
            return -1

        #Obtenemos las palabras de la respuesta
        words = result.decode().split()
        if len(words) == 0:
            #No hay respuesta suficiente
            print ("Error llamando usuario. El destinatario no respondio.")
            return -1
        elif words[0] == "CALL_ACCEPTED":
            #Acepta llamada
            if len(words) < 3:
                #Faltan datos
                print("Error en la respuesta del destinatario. No ha devuelto nick o puerto destino.")
                return -1
            #Hay timestamp
            print("Llamada aceptada por destinatario. Desea puerto: " + words[2])
            with self.global_lock:
                self.on_call_with[1] = words[2] #Ajustamos el puerto de llamada.

            return int(words[2])
        elif words[0] == "CALL_DENIED":
            #Rechaza llamada
            print("Destinatario rechaza llamada. Desconectando...")
            self.control_disconnect() #Desconectamos
            return -3
        elif words[0] == "CALL_BUSY":
            #Rechaza llamada
            print("Destinatario esta en llamada. Desconectando...")
            self.control_disconnect() #Desconectamos
            return -2
        #Respuesta desconocida
        print("Error desconocido llamando.")
        self.control_disconnect()
        return None

    def set_on_hold(self,held):
        '''
            Nombre: set_on_hold
            Descripcion: Pone en espera la llamada actual.
            Argumentos: held: true para poner en espera, false para reanudar.
            Retorno:
                0 si todo es correcto, -1 en caso de error.
        '''

        with self.global_lock:
            #Zona protegida porque opera con el estado y los sockets

            #Si no hay conexiones, error.
            if self.control_socket == None or self.connected_to == None:
                print ("Error poniendo en espera: no esta conectado con ningun usuario.")
                return None

            if self.on_call_with[0] == None or self.on_call_with[1] == None:
                print ("Error poniendo en espera: no esta en llamada.")
                return None

            if held:
                #Si se quiere pausar. Comprobamos que no este pausada ya.
                if self.on_hold:
                    print ("La llamada ya está en espera por parte de este extremo.")
                    return -1
                mensaje = "CALL_HOLD " + self.get_username()
                self.control_socket.send(mensaje.encode())
                print("Llamada puesta en espera.")
                self.on_hold = True
            else:
                #Si se quiere reanudar. Comprobamos que no este reanudada ya.
                if not self.on_hold:
                    print("La llamada ya está reanudada desde este extremo.")
                    return -1
                mensaje = "CALL_RESUME " + self.get_username()
                self.control_socket.send(mensaje.encode())
                print("Espera retirada de la llamada.")
                self.on_hold = False
        return 0

    def end_call(self):
        '''
            Nombre: end_call
            Descripcion: Finaliza la llamada actual. No termina la conexion (para ello, ver control_disconnect)
            Retorno:
                0 si todo es correcto, -1 en caso de error.
        '''

        with self.global_lock:
            #Zona protegida porque opera con el estado y los sockets.

            #Si no hay conexiones, error.
            if self.control_socket == None or self.connected_to == None:
                print ("Error finalizando llamada: no esta conectado con ningun usuario.")
                return -1

            if self.on_call_with[0] == None or self.on_call_with[1] == None:
                print ("Error finalizando llamada: no esta en llamada.")
                return -1

            mensaje = "CALL_END " + self.get_username()
            self.control_socket.send(mensaje.encode())

            self.on_call_with[1] = None
        return 0

    def send_loss_report(self, lost):
        '''
            Nombre: send_loss_report
            Descripcion: Envia un reporte de perdidas por la red.
            Retorno:
                0 si todo es correcto, -1 en caso de error.
        '''

        with self.global_lock:
            #Zona protegida porque opera con el estado y los sockets.

            #Si no hay conexiones, error.
            if self.control_socket is None or self.connected_to is None:
                print("Error enviando reporte: no esta conectado con ningun usuario.")
                return -1

            if self.on_call_with[0] is None or self.on_call_with[1] is None:
                print("Error enviando reporte: no esta en llamada.")
                return -1

            mensaje = "LOSS_REPORT " + str(lost) + " " + str(time.time())
            self.control_socket.send(mensaje.encode())
            print("Enviado reporte: " + mensaje)
        return 0

    def call_status(self):
        '''
            Nombre: call_status
            Descripcion: Permite al cliente saber si debe transferir/recibir video y a donde.
            Retorno:
                + Lista [ip,puerto] si el usuario esta en llamada. El video debe mandarse a esa ip+puerto.
                + Si la llamada esta en espera por nuestra parte, devuelve "HOLD1" en la ip
                + Si la llamada esta en espera por parte opuesta, devuelve "HOLD2" en la ip
                + Si no esta en llamada, devuelve None en la ip.
        '''

        with self.global_lock:
            if self.on_call_with[0] == None or self.on_call_with[1] == None:
                return [None,None]
            elif self.on_hold:
                return ["HOLD1", None]
            elif self.call_held:
                return ["HOLD2", None]
            else:
                return self.on_call_with

    #CONTROL ENTRANTE

    #Esta rutina se ejecutara en un hilo aparte de las demas, para controlar los comandos que entran.
    def control_incoming_loop(self,gui):
        '''
            Nombre: control_incoming_loop
            Descripcion: Gestiona el control entrante.
            Argumentos:
                gui: Interfaz para mostrar informacion
            Retorno:
                Imprime salida por pantalla. -1 en caso de error, 0 en caso correcto.
        '''

        with self.global_lock:
            incoming_end_read = self.incoming_end

        print("Hilo de procesado de comandos operativo.")
        while not incoming_end_read:
            self.connection_barrier.acquire() #Esperamos a que haya una conexion activa.

            with self.global_lock:
                if self.control_socket:
                    print("Conexion detectada. Hilo de procesado de mensajes intentando recibir...")

            if(self.control_socket != None):
                try:
                    msg = self.control_socket.recv(1024) #Recibimos mensaje
                except OSError:
                    self.connection_barrier.release()
                    self.control_disconnect()
                    print("Cerrando conexion de control (procesado de mensajes) actual ante el cierre por la parte contraria.")
                    with self.global_lock:
                        incoming_end_read = self.incoming_end
                    continue
                if not msg: #Si el otro cierra la conexion (EOF).
                    self.connection_barrier.release()
                    self.control_disconnect() #Cerramos la nuestra
                    print("Cerrando conexion de control (procesado de mensajes) actual ante el cierre por la parte contraria.")
                    with self.global_lock:
                        incoming_end_read = self.incoming_end
                    continue

                msg = msg.decode()

                print("Hilo de procesado de mensajes recibe: " + msg)
            else:
                self.connection_barrier.release()
                with self.global_lock:
                    incoming_end_read = self.incoming_end
                continue

            words = msg.split()
            will_end = False

            if(len(words) < 1):
                #El mensaje esta vacio
                self.connection_barrier.release()
                with self.global_lock:
                    incoming_end_read = self.incoming_end
                continue

            if(words[0] == "CALL_HOLD" and len(words) >= 2):
                print("El usuario " + words[1] + " pone la llamada en espera.")
                #Poner en espera
                with self.global_lock:
                    self.call_held = True
            elif(words[0] == "CALL_RESUME" and len(words) >= 2):
                print("El usuario " + words[1] + " retira su espera.")
                #Quitar espera
                with self.global_lock:
                    self.call_held = False
            elif(words[0] == "LOSS_REPORT" and len(words) >= 3):
                print("Reporte de perdidas recibido: " + words[1] + " perdidas, timestamp: " + words[2])
                self.video_buffer.set_loss_report(int(words[1]), float(words[2]))
            elif(words[0] == "CALL_END"):
                will_end = True

            self.connection_barrier.release()

            #Cerramos la conexion. Debe hacerse aqui despues para evitar
            #problemas con la barrera.
            if will_end:
                self.control_disconnect()
                will_end = False
                gui.infoBox("Llamada finalizada.", "El otro usuario ha terminado la llamada.")

            #Recuperamos el estado del bucle
            with self.global_lock:
                incoming_end_read = self.incoming_end

        print("Hilo de procesado de mensajes saliendo...")

    def control_incoming_stop(self):
        '''
            Nombre: control_incoming_stop
            Descripcion: Detiene el procesamiento de mensajes de control entrantes
        '''
        with self.global_lock:
            self.incoming_end = True
            self.connection_barrier.release() #Levantamos la barrera para que en cualquier caso pueda salir.


    #ESCUCHA DE CONEXIONES NUEVAS

    #Esta rutina se ejecutara en un hilo aparte de las demas, para poder estar a la escucha. Por tanto usaremos Locks para proteger
    #las globales que modifique
    def control_listen_loop(self,port,gui):
        '''
            Nombre: control_listen_loop
            Descripcion: Establece un socket TCP a la escucha en el puerto pasado y gestiona las nuevas conexiones.
            Argumentos:
                    port: puerto de escucha como cadena. Por ejemplo "1234"
                    gui: Objeto interfaz grafica para mostrar una informacion cuando nos esten llamando.
            Retorno:
                Imprime salida por pantalla. -1 en caso de error, 0 en caso correcto.
        '''
        socket_escucha = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if socket_escucha == None:
            print("Error abriendo socket para escuchar conexiones de control.")
            return -1

        #Asociar al puerto
        self.tcp_port = port #Esto es para registrar el puerto.
        socket_escucha.bind(('', int(port)))

        socket_escucha.listen(5) #Escuchar

        with self.global_lock:
            listen_end_read = self.listen_end

        #Bucle que se ejecutara continuamente.
        print("Hilo de escucha de peticiones operativo en puerto: " + port)
        while not listen_end_read:

            #Aceptar conexion
            try:
                connection, addr = socket_escucha.accept()
            #Esto es para salir cuando acabe el programa. El accept saldra y entrara aqui.
            except OSError:
                with self.global_lock:
                    listen_end_read = self.listen_end
                continue
            print ("Aceptada conexion desde " + addr[0] + ":" + str(addr[1]))

            #Vemos a ver si esta intentando llamar.
            connection.settimeout(self.socket_timeout) #Ponemos un timeout por si no responden
            try:
                msg = connection.recv(1024)
            except socket.timeout:
                print ("Conexion rechazada ante la falta de comandos.")
                connection.close()
                with self.global_lock:
                    listen_end_read = self.listen_end
                continue
            connection.settimeout(None)

            if not msg: #En caso de que nos cierren la conexion.
                connection.close()
                with self.global_lock:
                    listen_end_read = self.listen_end
                continue

            msg = msg.decode()
            words = msg.split()

            print("Conexion entrante pide: " + msg)
            #Si no esta intentando llamar cerramos
            if(len(words) < 3 or words[0] != "CALLING"):
                print("Llamada denegada por peticion malformada: " + msg)
                end_call = "CALL_DENIED " + self.get_username()
                connection.send(end_call.encode())
                connection.close()
                with self.global_lock:
                    listen_end_read = self.listen_end
                continue

            #Si ya estamos conectados estamos ocupados.
            with self.global_lock:
                connected_to_read = self.connected_to
                control_socket_read = self.control_socket
            if(connected_to_read != None or control_socket_read != None):
                print("Ya hay una conexion activa. Respondiendo a " + words[1] + " como llamada ocupada.")
                connection.send(b'CALL_BUSY')
                connection.close()
                with self.global_lock:
                    listen_end_read = self.listen_end
                continue
            #Comprobar si el usuario rechaza la conexion
            accepted = gui.yesNoBox("Llamada entrante.", words[1] + " esta llamando. Desea coger la llamada?")
            if not accepted:
                print("Llamada rechazada. Informando a " + words[1] + " y cortando su conexion...")
                call_denied = "CALL_DENIED " + self.get_username()
                connection.send(call_denied.encode())
                connection.close()
                with self.global_lock:
                    listen_end_read = self.listen_end
                continue

            #Obtenemos que version esta usando la otra parte:
            ret = self.discovery.query_user(words[1])
            if "V1" in ret[2]:
                uses_v1 = True
                print("Llamante usa V1")
            else:
                uses_v1 = False
                print("Llamante no usa V1")

            #Si no, esta pasa a ser la conexion actual
            with self.global_lock:
                print("Llamada aceptada. Cambiando conexion de control actual...")
                self.control_socket = connection
                self.connected_to = words[1]
                if uses_v1:
                    self.video_buffer.set_using_v1()
                self.on_call_with = [addr[0], words[2]]
                self.on_hold = False
                self.call_held = False
                self.connection_barrier.release() #Levantamos la barrera de conexion
                start_call = "CALL_ACCEPTED " + self.get_username() + " " + self.get_video_port()
                sent = connection.send(start_call.encode())
                listen_end_read = self.listen_end
            if not sent: #Esto ocurre si antes de que aceptemos nos han cerrado.
                self.control_disconnect()

        socket_escucha.close()
        print("Hilo de escucha de peticiones saliendo...")
        return 0

    def control_listen_stop(self):
        '''
            Nombre: control_listen_stop
            Descripcion: Detiene la escucha de nuevas conexiones
        '''

        with self.global_lock:
            self.listen_end = True

        #Evita bloqueo en accept. No basta con cerrar el socket de escucha, por desgracia:
        #En algunos OS seguira estando bloqueado. Por tanto, nos conectam0os
        #para desbloquear el accept en caso de que sea necesario.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("localhost",int(self.tcp_port)))
        s.close()
