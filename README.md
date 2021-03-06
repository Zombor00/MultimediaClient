# practica3

Tercera práctica de la asignatura REDES II. Creación de un cliente de video en tiempo real.
Autores: Alejandro Bravo de la Serna y Miguel González González.

## Utilización del cliente. Preparación
Para usar el cliente a través de la red será necesario habilitar un puerto TCP y un puerto UDP. 
Si se está en un equipo detrás de un NAT, habrá que indicar al router que permita el tráfico TCP y UDP,
cada uno por un puerto a elegir (superior a 1024), y lo reenvíe a la máquina desde la
que se ejecuta el cliente. Asimismo, si se dispone de un firewall en algun punto, deberá permitirse
el paso de los paquetes con esos puertos. Para usar el cliente en local no es necesario, lógicamente.

## Fichero de configuración
Al inicio del programa se carga el fichero config.json con distintos valores usados por el cliente. 

El fichero tiene los siguientes campos:

*  BUFFER_SIZE: Tamaño del buffer de recepción de frames.
*  BUFFER_THRESHOLD: Frames a cargar en el buffer antes de reproducir video.
*  FIXED\_DELAY\_THRESHOLD: Margen mínimo de retardo para tirar paquetes.
*  FPS_REFRESH: Cada cuantos segundos se recalculan los fps.
*  QUALITY_REFRESH: Cada cuantos segundos se recalcula la calidad de compresión.
*  RESOLUTION_REFRESH: Cada cuantos segundos se recalcula la resolución a la que se envía el frame.
*  call_timeout: Tiempo máximo (en segundos) para esperar respuesta en una llamada
*  user_filename: Nombre del fichero del que se carga información del último usuario que uso la aplicación.
*  server_ip: IP del server de descubrimiento.
*  server_port: Puerto en la que se encuentra el servidor de descubrimiento.
*  REPORT_REFRESH: Cada cuanto se envía al otro usuario un report con los paquetes perdidos.
*  REPORT_WEIGHT: Fracción que pondera el valor de los reportes frente a los cáclulos propios. Se tiene que encontrar entre 0 y 1.

Si se nota cierto delay o los fps de la cámara son bajos se recomeinda poner un BUFFER_THRESHOLD menor para reducir el delay.
Si se nota que no llega el vídeo se puede deber a que el FIXED\_DELAY\_THRESHOLD se ha configurado muy bajo.

## Registro del usuario
Al lanzarse la aplicación ejecutando _python3 practica3_client.py_ , el cliente se conecta al servidor de descubrimiento para registrar al usuario.
(En caso de que esta conexión falle (por ejemplo, porque no se disponga de conexión a internet, o el servidor
este caído), la aplicación se cerrará mostrando un mensaje de error).

Cuando la conexión ha sido exitosa, se pedirán los siguientes campos:

*  Nick: Un nombre de usuario.
*  Password: Una clave para iniciar sesión posteriormente.
*  Puerto de control (TCP): El puerto TCP que se ha habilitado
*  Puerto de control (UDP): El puerto UDP que se ha habilitado
*  IP: La IP de internet a través de la que se puede acceder al cliente. 
Si la máquina está detrás de un NAT, por tanto, debe ser la IP del router.
El cliente tratará de autocompletar este campo mediante un servicio externo, pero lo dejará en blanco si no puede.
Para usar el cliente en local, se puede introducir la IP de una de las interfaces de la máquina, o dejarla en blanco.
Si se deja en blanco, se asignará automáticamente la IP de una de las interfaces de la máquina.

Si el nick ya está en el servidor de descubrimiento, la clave debe coincidir con la que se usó para registrarlo por primera vez.
Por tanto, si se obtiene un error de clave incorrecta y es la primera vez que se trata de registrar al usuario, el motivo es que
otra persona ya lo ha registrado.

## Selección de vídeo
El cliente trata de abrir una cámara tras registrarse el usuario. Con los botones de la parte superior del cliente se puede cambiar
entre cámara y fichero de vídeo, aunque cabe mencionar que el cliente ajustará los FPS según la calidad de la transmisión, luego es posible
que el vídeo se capture acelerado o ralentizado, a causa de este ajuste que difiere de los FPS a los que se grabó.

## Realización de llamadas
Con el botón _conectar_ se puede llamar a un usuario introduciendo su nombre. También se muestra una lista con los nombres registrados en el servidor,
para poder seleccionar de ahí. Tras ello, se intentará llamar al usuario y, si este responde, la llamada iniciará automáticamente, mostrando su vídeo.

(_Disclaimer: Este cliente utiliza todos los campos de las cabeceras del protocolo V0 para el ajuste del vídeo, luego si se usa algún otro cliente que no sea este 
y que ignore estas cabeceras o las ajuste erróneamente, es posible que el vídeo entrante no se muestre o lo haga de manera incorrecta._)

## Información de estado
En la barra de estado (parte inferior del cliente) se mostrará información relevante. En la parte izquierda se muestra el estado de la llamada actual.
En la parte central se muestran los parámetros del vídeo que se está enviando. En la parte derecha se muestran los parámetros del vídeo que se está recibiendo,
y la duración de la llamada.

## Control en llamada
Durante una llamada, el usuario puede hacer clic en _Espera_ para poner la llamada en espera, lo que causará que no se envíe ni reciba vídeo. La espera es individual,
es decir, un usuario puede poner la llamada en espera y posteriormente el otro también. Hasta que los 2 usuarios no retiren su espera, no continuará la llamada. En la
parte inferior izquierda (barra de estado), se puede ver en todo momento quién ha puesto la llamada en espera.

Asimismo, se puede finalizar la llamada pulsando el botón de _colgar_ (para realizar otra llamada posterior), o saliendo de la aplicación.

## Pruebas realizadas
Hemos probado el funcionamiento tanto en local como a través de la red entre nosotros y contra clientes de otros compañeros y no hemos detectado ningún problema. También hemos probado con el script _simulate_internet.sh_, 
en local, y se aprecian las pérdidas y retardos por lo que el programa baja la calidad como se espera. Cuando probamos en local con los 2 clientes por loopback con la corrupción de paquetes,
funciona correctamente aunque a veces algunos mensajes TCP que no deberían perderse dan algún fallo, quizás debido a la corrupción de los paquetes de control TCP (no estamos seguros).

