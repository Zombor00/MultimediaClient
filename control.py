'''
    control.py
    Modulo que se encarga de emitir las conexiones de control.
    Incluye la funcion de escucha de conexiones de control.
    @author Miguel Gonzalez, Alejandro Bravo.
    @version 1.0
    @date 22-04-2020
'''

'''
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
from discovery import query_user
import threading
import json

# Parametros
socket_timeout = 3 #Timeout para receive en casos criticos.
call_timeout = 15 #Timeout para responder a la llamada
user_filename = "usuario.json" #Fichero de usuario

# ESTADO ACTUAL

control_socket = None #Socket de control.
connected_to = None #Nombre del usuario al que esta conectado.
on_call_with = [None,None] #IP y puerto (como cadena) para transferencia de video. Si alguno es None, no esta en llamada.
on_hold = False #Indica si se ha puesto la llamada en espera
call_held = False #Indica si la otra parte ha puesto la llamada en espera.
listen_end = False #Indica al hilo que escucha que debe parar.
incoming_end = False #Indica al hilo que responde comandos entrantes que debe parar.
connection_barrier = threading.Semaphore(0) #Barrera que impide el paso al hilo que responde comandos si no hay conexiones activas.
global_lock = threading.Lock() #Cerrojo para las variables globales.
tcp_port = 0 #Puerto de control para poder cerrarlo.
udp_port = None #Puerto de entrada de video
username = None #Nombre de usuario propio


# INFORMACION 
def get_username():
    '''
        Nombre: get_username
        Descripcion: Obtiene el nombre de usuario propio.
        Argumentos: 
        Retorno:
            Nombre de usuario
    '''
    global username
    data = None
    if not username:
        try:
            with open(user_filename, "r") as file:
                data = json.load(file)
        except:
            print("Error abriendo fichero de usuario.")
            control_disconnect() #Desconectamos del usuario actual.
            return "Error"
        username = data["username"]
    return username

def get_video_port():
    '''
        Nombre: get_video_port
        Descripcion: Obtiene el puerto en el que se recibe el video.
        Argumentos: 
        Retorno:
            Puerto en el que se recibe el video.
    '''
    global udp_port
    data = None
    if not udp_port:
        try:
            with open(user_filename, "r") as file:
                data = json.load(file)
        except:
            print("Error abriendo fichero de usuario.")
            control_disconnect() #Desconectamos del usuario actual.
            return "Error"
        udp_port = data["udp_port"]
    return udp_port

def get_connected_username():
    '''
        Nombre: get_connected_username
        Descripcion: Obtiene el nombre del usuario con el que esta conectado.
        Argumentos: 
        Retorno:
            Usuario con el que esta conectado o None.
    '''
    connected_to
    with global_lock:
        return connected_to


# CONTROL SALIENTE

def connect_to(username):
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
    global connected_to, on_hold, on_call_with, call_held,global_lock

    with global_lock:
        connected_to_read = connected_to

    if connected_to_read != None:
        print("Error conectandose al usuario indicado. Ya esta conectado al usuario: " + connected_to_read)
        return -1

    #Obtenemos la IP y el puerto.
    ret = query_user(username)
    if ret == None:
        print("Error conectandose al usuario indicado. El servidor reporta que no existe.")
        return -1
    if connect_to_addr(ret[0],ret[1]) == -1:
        return -1
    
    #Ajuste de parametros
    with global_lock:
        connected_to = username
        on_hold = False #Reinicia la espera de la llamada.
        call_held = False
        on_call_with = [ret[0], None] #Vamos ajustando la IP de video
    return call(int(get_video_port())) #Se efectua la llamada
    
def connect_to_addr(ip, port):
    '''
        Nombre: connect_to_addr
        Descripcion: Inicializa la conexion de control con un usuario.
        Argumentos: ip: Ip a la que conectarse.
                    port: puerto al que conectarse.
        Retorno:
            0 si todo ha ido correctamente, -1 en caso de error.
    '''
    global control_socket, connected_to, on_hold,global_lock

    with global_lock:
        #Zona protegida porque tocamos el socket global. 
        #Ademas esto se ejecuta puntualmente (cuando el usuario llama), asi que no 
        #interfiere en exceso con los hilos en bucle.

        if(control_socket != None):
            print("Ya hay una conexion de control establecida. Debe cerrarse primero.")
            return -1

        control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if control_socket == None:
            return -1

        print("Conectandose al usuario con ip " + ip + " y puerto " + port)
        try:
            control_socket.settimeout(call_timeout)
            control_socket.connect((ip,int(port)))
            control_socket.settimeout(None)
        except:
            print ("No ha sido posible conectarse al usuario. El usuario no ha aceptado la conexion en el tiempo establecido.")
            control_socket.close()
            control_socket = None
            return -1

    return 0

def control_disconnect():
    '''
        Nombre: control_disconnect
        Descripcion: Finaliza la conexion de control saliente abierta previamente.
        Argumentos: 
        Retorno:
            0 si todo ha ido correctamente, -1 en caso de error.
    '''
    global control_socket, connected_to, on_hold, on_call_with, connection_barrier, global_lock

    with global_lock:

    #Zona protegida porque altera el estado.
        if control_socket == None:
            print ("Se ha intentado enviar un comando por la conexion de control sin estar conectado a el.")
            return -1
        control_socket.close()

        #Reinicio de variables
        control_socket = None
        connected_to = None
        on_hold = False
        on_call_with = [None, None]
    connection_barrier.acquire() #Bajamos el semaforo de conexion
    return 0

def call(dstport):
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
    global control_socket, connected_to, on_call_with, global_lock, connection_barrier

    with global_lock:
        #Zona protegida por operar con el socket
        if control_socket == None or connected_to == None:
            print ("Error llamando: no se esta conectado a ningun usuario.")
            return None
        mensaje = "CALLING " + get_username() + " " + str(dstport)
        control_socket.send(mensaje.encode())

    with global_lock:
        #Por si cambia la conexion, guardamos el socket actual. Esto es para no bloquear el lock durante receive que puede tardar.
        control_socket_read = control_socket

    try:
        #try except por si nos han cerrado el socket, y para el timeout.
        control_socket_read.settimeout(call_timeout)
        result = control_socket_read.recv(1024)
        control_socket_read.settimeout(None)
    except:
        print("Error iniciando llamada: el otro lado no ha respondido. Cerrando conexion...")
        connection_barrier.release() #Para que pueda hacerse la desconexion
        control_disconnect()
        return -1

    connection_barrier.release() #Subimos el semaforo de conexion, ya solo leera el otro hilo

    if not result:
        #El otro ha cerrado la conexion. El hilo de procesado de comandos cerrara nuestro lado. Salimos
        print("Error iniciando llamada: el otro extremo ha cerrado la conexion.")
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
        with global_lock:
            on_call_with[1] = words[2] #Ajustamos el puerto de llamada.

        return int(words[2])
    elif words[0] == "CALL_DENIED":
        #Rechaza llamada
        print("Destinatario rechaza llamada. Desconectando...")
        control_disconnect() #Desconectamos
        return -3
    elif words[0] == "CALL_BUSY":
        #Rechaza llamada
        print("Destinatario esta en llamada. Desconectando...")
        control_disconnect() #Desconectamos
        return -2
    #Respuesta desconocida
    print("Error desconocido llamando.")
    return None

def set_on_hold(held):
    '''
        Nombre: set_on_hold
        Descripcion: Pone en espera la llamada actual.
        Argumentos: held: true para poner en espera, false para reanudar.
        Retorno:
            0 si todo es correcto, -1 en caso de error.
    '''
    global control_socket, connected_to, on_hold, on_call_with, global_lock

    with global_lock:
        #Zona protegida porque opera con el estado y los sockets

        #Si no hay conexiones, error.
        if control_socket == None or connected_to == None:
            print ("Error poniendo en espera: no esta conectado con ningun usuario.")
            return None

        if on_call_with[0] == None or on_call_with[1] == None:
            print ("Error poniendo en espera: no esta en llamada.")
            return None

        if held:
            #Si se quiere pausar. Comprobamos que no este pausada ya.
            if on_hold:
                print ("La llamada ya está en espera por parte de este extremo.")
                return -1
            mensaje = "CALL_HOLD " + get_username()
            control_socket.send(mensaje.encode())
            print("Llamada puesta en espera.")
            on_hold = True
        else:
            #Si se quiere reanudar. Comprobamos que no este reanudada ya.
            if not on_hold:
                print("La llamada ya está reanudada desde este extremo.")
                return -1
            mensaje = "CALL_RESUME " + get_username()
            control_socket.send(mensaje.encode())
            print("Espera retirada de la llamada.")
            on_hold = False
    return 0

def end_call():
    '''
        Nombre: end_call
        Descripcion: Finaliza la llamada actual. No termina la conexion (para ello, ver control_disconnect)
        Retorno:
            0 si todo es correcto, -1 en caso de error.
    '''
    global control_socket, connected_to, on_hold, on_call_with, global_lock

    with global_lock:
        #Zona protegida porque opera con el estado y los sockets.

        #Si no hay conexiones, error.
        if control_socket == None or connected_to == None:
            print ("Error finalizando llamada: no esta conectado con ningun usuario.")
            return -1

        if on_call_with[0] == None or on_call_with[1] == None:
            print ("Error finalizando llamada: no esta en llamada.")
            return -1

        mensaje = "CALL_END " + get_username()
        control_socket.send(mensaje.encode())

        on_call_with[1] = None
    return 0

def call_status():
    '''
        Nombre: call_status
        Descripcion: Permite al cliente saber si debe transferir/recibir video y a donde.
        Retorno:
            + Lista [ip,puerto] si el usuario esta en llamada. El video debe mandarse a esa ip+puerto.
            + Si la llamada esta en espera por nuestra parte, devuelve "HOLD1" en la ip
            + Si la llamada esta en espera por parte opuesta, devuelve "HOLD2" en la ip
            + Si no esta en llamada, devuelve None en la ip.
    '''
    global on_hold, on_call_with, call_held, global_lock

    with global_lock:
        if on_call_with[0] == None or on_call_with[1] == None:
            return [None,None]
        elif on_hold:
            return ["HOLD1", None]
        elif call_held:
            return ["HOLD2", None]
        else:
            return on_call_with


#CONTROL ENTRANTE

#Esta rutina se ejecutara en un hilo aparte de las demas, para controlar los comandos que entran.
def control_incoming_loop(gui):
    '''
        Nombre: control_incoming_loop
        Descripcion: Gestiona el control entrante.
        Argumentos:
            gui: Interfaz para mostrar informacion
        Retorno:
            Imprime salida por pantalla. -1 en caso de error, 0 en caso correcto.
    '''
    global connection_barrier, incoming_end, global_lock, call_held, control_socket

    with global_lock:
        incoming_end_read = incoming_end

    print("Hilo de procesado de comandos operativo.")
    while not incoming_end_read:
        connection_barrier.acquire() #Esperamos a que haya una conexion activa.

        with global_lock:
            if control_socket:
                print("Conexion detectada. Hilo de procesado de mensajes intentando recibir...")
        
        if(control_socket != None):
            try:
                msg = control_socket.recv(1024) #Recibimos mensaje
            except:
                connection_barrier.release()
                control_disconnect()
                print("Cerrando conexion de control actual ante el cierre por la parte contraria.")
                with global_lock:
                    incoming_end_read = incoming_end
                continue 
            if not msg: #Si el otro cierra la conexion (EOF).
                connection_barrier.release()
                control_disconnect() #Cerramos la nuestra
                print("Cerrando conexion de control actual ante el cierre por la parte contraria.")
                with global_lock:
                    incoming_end_read = incoming_end
                continue
            
            msg = msg.decode()

            print("Hilo de procesado de mensajes recibe: " + msg)
        else:
            connection_barrier.release()
            with global_lock:
                incoming_end_read = incoming_end
            continue

        words = msg.split()
        will_end = False

        if(len(words) < 1):
            #El mensaje esta vacio
            connection_barrier.release()
            with global_lock:
                incoming_end_read = incoming_end
            continue

        if(words[0] == "CALL_HOLD" and len(words) >= 2):
            print("El usuario " + words[1] + " pone la llamada en espera.")
            #Poner en espera
            with global_lock:
                call_held = True
        elif(words[0] == "CALL_RESUME" and len(words) >= 2):
            print("El usuario " + words[1] + " retira su espera.")
            #Quitar espera
            with global_lock:
                call_held = False
        elif(words[0] == "CALL_END"):
            will_end = True

        connection_barrier.release()

        #Cerramos la conexion. Debe hacerse aqui despues para evitar
        #problemas con la barrera.
        if will_end:
            control_disconnect()
            will_end = False
            gui.infoBox("Llamada finalizada.", "El otro usuario ha terminado la llamada.")

        #Recuperamos el estado del bucle
        with global_lock:
            incoming_end_read = incoming_end

    print("Hilo de procesado de comandos saliendo...")

def control_incoming_stop():
    '''
        Nombre: control_incoming_stop
        Descripcion: Detiene el procesamiento de mensajes de control entrantes
    '''
    global incoming_end, global_lock, connection_barrier
    with global_lock:
        incoming_end = True
        connection_barrier.release() #Levantamos la barrera para que en cualquier caso pueda salir.


#ESCUCHA DE CONEXIONES NUEVAS

#Esta rutina se ejecutara en un hilo aparte de las demas, para poder estar a la escucha. Por tanto usaremos Locks para proteger
#las globales que modifique
def control_listen_loop(port,gui):
    '''
        Nombre: control_listen_loop
        Descripcion: Establece un socket TCP a la escucha en el puerto pasado y gestiona las nuevas conexiones.
        Argumentos:
                port: puerto de escucha como cadena. Por ejemplo "1234"
                gui: Objeto interfaz grafica para mostrar una informacion cuando nos esten llamando.
        Retorno:
            Imprime salida por pantalla. -1 en caso de error, 0 en caso correcto.
    '''
    global listen_end,connected_to,control_socket,on_call_with, on_hold, call_held,connection_barrier, global_lock,tcp_port

    socket_escucha = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if socket_escucha == None:
        print("Error abriendo socket para escuchar conexiones de control.")
        return -1
    
    #Asociar al puerto
    tcp_port = port #Esto es para registrar el puerto.
    socket_escucha.bind(('', int(port)))

    socket_escucha.listen(5) #Escuchar

    with global_lock:
        listen_end_read = listen_end

    #Bucle que se ejecutara continuamente.
    print("Hilo de escucha de peticiones operativo en puerto: " + port)
    while not listen_end_read:

        #Aceptar conexion
        try:
            connection, addr= socket_escucha.accept()
        #Esto es para salir cuando acabe el programa. El accept saldra y entrara aqui.
        except:
            with global_lock:
                listen_end_read = listen_end
            continue
        print ("Aceptada conexion desde " + addr[0] + ":" + str(addr[1]))

        #Vemos a ver si esta intentando llamar.
        connection.settimeout(socket_timeout) #Ponemos un timeout por si no responden
        try:
            msg = connection.recv(1024)
        except socket.timeout:
            print ("Conexion rechazada ante la falta de comandos.")
            connection.close()
            with global_lock:
                listen_end_read = listen_end
            continue
        connection.settimeout(None)

        if not msg: #En caso de que nos cierren la conexion.
            connection.close()
            with global_lock:
                listen_end_read = listen_end
            continue

        msg = msg.decode()
        words = msg.split()

        print("Conexion entrante pide: " + msg)
        #Si no esta intentando llamar cerramos
        if(len(words) < 3 or words[0] != "CALLING"):
            print("Llamada denegada por peticion malformada: " + msg)
            end_call = "CALL_DENIED " + get_username()
            connection.send(end_call.encode())
            connection.close()
            with global_lock:
                listen_end_read = listen_end
            continue

        #Si ya estamos conectados estamos ocupados.
        with global_lock:
            connected_to_read = connected_to
            control_socket_read = control_socket
        if(connected_to_read != None or control_socket_read != None):
            print("Ya hay una conexion activa. Respondiendo a " + words[1] + " como llamada ocupada.")
            connection.send(b'CALL_BUSY')
            connection.close()
            with global_lock:
                listen_end_read = listen_end
            continue
        #Comprobar si el usuario rechaza la conexion
        accepted = gui.yesNoBox("Llamada entrante.", words[1] + " esta llamando. Desea coger la llamada?")
        if not accepted:
            print("Llamada rechazada. Informando a " + words[1] + " y cortando su conexion...")
            call_denied = "CALL_DENIED " + get_username()
            connection.send(call_denied.encode())
            connection.close()
            with global_lock:
                listen_end_read = listen_end
            continue

        #Si no, esta pasa a ser la conexion actual
        with global_lock:
            print("Llamada aceptada. Cambiando conexion de control actual...")
            control_socket = connection
            connected_to = words[1]
            on_call_with = [addr[0],words[2]]
            on_hold = False
            call_held = False
            connection_barrier.release() #Levantamos la barrera de conexion
            start_call = "CALL_ACCEPTED " + get_username() + " " + get_video_port()
            sent = connection.send(start_call.encode())
            listen_end_read = listen_end
        if not sent: #Esto ocurre si antes de que aceptemos nos han cerrado.
            control_disconnect()

    socket_escucha.close()
    print("Hilo de escucha de peticiones saliendo...")
    return 0

def control_listen_stop():
    '''
        Nombre: control_listen_stop
        Descripcion: Detiene la escucha de nuevas conexiones
    '''
    global listen_end, global_lock,tcp_port

    with global_lock:
        listen_end = True

    #Evita bloqueo en accept. No basta con cerrar el socket de escucha, por desgracia:
    #En algunos OS seguira estando bloqueado. Por tanto, nos conectam0os
    #para desbloquear el accept en caso de que sea necesario.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("localhost",int(tcp_port)))
    s.close()
