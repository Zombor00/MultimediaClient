'''
    discovery.py
    Modulo que se encarga de la comunicacion con el servidor de descubrimiento.
    @author Miguel Gonzalez, Alejandro Bravo.
    @version 1.0
    @date 22-04-2020
'''

import socket

class Discovery():
    '''Clase de descubrimiento: mantiene el estado y las funcionalidades del modulo de descubrimiento'''

    socket_timeout = 3 #Timeout para la conexion
    server_socket = None #Socket del servidor.
    server_ip = "vega.ii.uam.es" #Parametro con la IP
    server_port = 8000 #Parametro con el puerto

    def __init__(self, server_ip, server_port):
        '''
            Nombre: __init__
            Descripcion: Inicializa la conexion con el servidor
            Argumentos: server_ip : Valor de la IP de discovery.
                        server_port: Valor del puerto de discovery.
            Retorno:
                Lanza una excepcion generica si algo va mal.
        '''
        self.server_ip = server_ip
        self.server_port = server_port

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.server_socket == None:
            raise Exception("Error abriendo socket de descubrimiento.")

        print("Conectandose al servidor de descubrimiento...")
        try:
            self.server_socket.settimeout(self.socket_timeout)
            self.server_socket.connect((self.server_ip,self.server_port))
            self.server_socket.settimeout(None)
        except:
            #Timeout
            self.server_socket.close()
            self.server_socket = None
            raise Exception("La conexion al server de descubrimiento ha dado timeout.")

    def server_quit(self):
        '''
            Nombre: server_quit
            Descripcion: Termina la conexion con el servidor, informando al server y limpiando recursos.
            Argumentos:
            Retorno:
                0 si todo ha ido correctamente, -1 en caso de error.
        '''
        if self.server_socket == None:
            print ("Se ha intentado enviar un comando al servidor sin estar conectado a el.")
            return -1
        self.server_socket.send(b'QUIT')
        result = self.server_socket.recv(1024)
        if result.decode() != "BYE":
            print ("Advertencia: El servidor no ha respondido al server_quit. Cerrando conexion...")
        self.server_socket.close()
        print("Desconectado del servidor de descubrimiento.")
        self.server_socket = None
        return 0

    def register_user(self, nickname, password, ip, port, protocols):
        '''
            Nombre: register_user
            Descripcion: Registra un usuario en el sistema.
            Argumentos: nickname: Nombre de usuario a registrar.
                        password: Clave del usuario
                        protocols: Lista de protocolos que soporta
                        ip: Direccion IP desde la que escucha
                        port: Puerto desde el que escucha
            Retorno:
                Timestamp de registro, -1 en caso de clave incorrecta o None en caso de error.
        '''
        if self.server_socket == None:
            print ("Se ha intentado enviar un comando al servidor sin estar conectado a el.")
            return None
        cadena_protocolos = "#".join(protocols) #Creamos la cadena como especifica el protocolo
        mensaje = "REGISTER " + nickname + " " + ip + " " + port + " " + password + " " + cadena_protocolos
        self.server_socket.send(mensaje.encode())
        result = self.server_socket.recv(1024)

        #Obtenemos las palabras de la respuesta
        words = result.decode().split()
        if len(words) < 2:
            #No hay respuesta suficiente
            print ("Error registrando usuario. El servidor no respondio.")
            return None
        elif words[0] == "OK" and words[1] == "WELCOME":
            #Respuesta correcta
            if len(words) < 3:
                #No hay timestamp
                print("Usuario registrado correctamente. El servidor no ha proporcionado timestamp.")
                return "0"
            #Hay timestamp
            print("Usuario registrado correctamente en timestamp: " + words[3])
            return words[2]
        elif words[0] == "NOK" and words[1] == "WRONG_PASS":
            #Respuesta incorrecta
            print("Error registrando usuario. Contrase??a incorrecta.")
            return -1
        #Respuesta desconocida
        print("Error desconocido registrando usuario.")
        return None

    def query_user(self,nickname):
        '''
            Nombre: query_user
            Descripcion: Busca la informacion del usuario dado en el sistema.
            Argumentos: nickname: Nombre del usuario.
            Retorno:
                Lista con IP, puerto y lista de protocolos soportados por el cliente, todo como cadenas. None en caso de error.
        '''
        if self.server_socket == None:
            print ("Se ha intentado enviar un comando al servidor sin estar conectado a el.")
            return None
        mensaje = "QUERY " + nickname
        self.server_socket.send(mensaje.encode())
        result = self.server_socket.recv(1024)
        words = result.decode().split()
        if len(words) < 2:
            #No hay respuesta suficiente
            print ("Error buscando usuario. El servidor no respondio.")
            return None
        elif words[0] == "OK" and words[1] == "USER_FOUND":
            #Respuesta correcta
            if len(words) < 6:
                #No hay datos en la respuesta
                print("Error en QUERY: El servidor ha reportado que existe el usuario, pero no ha devuelto sus datos.")
                return -1
            #Hay datos en la respuesta
            print("Usuario " + words[2] + " encontrado correctamente con IP: " + words[3] + ", puerto: " + words[4] + " y protocolos: " + words[5])
            lista_protocolos = words[5].split("#")
            return [words[3],words[4],lista_protocolos]
        elif words[0] == "NOK" and words[1] == "USER_UNKNOWN":
            #Respuesta incorrecta
            print("Error buscando usuario: No existe usuario con ese nombre.")
            return None
        #Respuesta desconocida.
        print("Error desconocido buscando usuario.")
        return None

    def list_users(self):
        '''
            Nombre: list_users
            Descripcion: Muestra un listado de todos los usuarios en el sistema.
            Argumentos:
            Retorno:
                Lista con los datos de cada usuario. Cada dato es [nick ip port ts]. None en caso de error.
        '''
        if self.server_socket == None:
            print ("Se ha intentado enviar un comando al servidor sin estar conectado a el.")
            return None
        mensaje = "LIST_USERS"
        self.server_socket.send(mensaje.encode())

        #Recibir la cantidad adecuada de usuarios
        continue_receiving = True
        result = bytes()
        while continue_receiving:
            result += self.server_socket.recv(1024)
            result_str = result.decode()
            words = result_str.split() #Queremos la tercera palabra que trae cuantos users hay

            #??Por que este codigo tan raro, en lugar de result_str.count(#)? Pues porque algun
            #gracioso se ha puesto de username: "mua#ja#ja#ja", y el server no lo prohibe.
            #Por tanto contamos como maximo un # por palabra...
            if int(words[2]) <= len([1 for e in words[3:] if '#' in e]):
                continue_receiving = False
                
        if len(words) < 2:
            #No hay respuesta suficiente
            print ("Error listando usuarios. El servidor no respondio.")
            return None
        elif words[0] == "OK" and words[1] == "USERS_LIST":
            #Respuesta correcta
            if len(words) < 3:
                #No hay datos en la respuesta
                print("Advertencia en LIST: El servidor no ha devuelto ningun usuario.")
                return []
            #Obtenemos lista de usuarios.
            lista_usuarios = " ".join(words[3:]).split("#") #A partir de la palabra 3 estan los usuarios
            lista_usuarios = lista_usuarios[:-1] #Eliminamos el espacio en blanco final.

            #Los imprimimos
            i = 1
            print(str(len(lista_usuarios)) + " usuarios encontrados: ")
            for usuario in lista_usuarios:
                print(str(i) + ": " + usuario)
                i += 1

            return list(map(lambda x : x.split() , lista_usuarios))

        elif words[0] == "NOK" and words[1] == "USER_UNKNOWN":
            #Respuesta incorrecta
            print("Error listando usuarios. Servidor da respuesta erronea.")
            return None
        #Respuesta desconocida.
        print("Error desconocido listando usuarios.")
        return None
