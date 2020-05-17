# Cambios respecto de la entrega temprana

1. Se ha convertido el código para utilizar objetos, atributos y métodos
en lugar de variables globales de estado, como se sugirió.

2. Se ha incluido un fichero de configuración del que leer valores relevantes
para la ejecución del programa. Está explicado en README.md.

3. Se ha introducido e implementado un protocolo V1, que viene explicado en la
wiki del proyecto y permite ajustar la calidad según las pérdidas en el otro
extremo.

4. Se ha actualizado la wiki del proyecto para reflejar estos cambios.

5. Acerca de la función update_screen, nos gustaría comentar que solo se llama
cuando ya se tiene el frame que hay que pintar, y es llamada tanto por el hilo
de recepcion como por el de envío. De esta manera, en cuanto hay disponible
un frame (el que toca sacar del buffer o el grabado por la cámara), se pinta
en la pantalla. Almacenamos también una copia de los últimos frames pintados,
para que si cada hilo va a un ritmo de FPS distinto, se pueda realizar la
actualización de pantalla sin tener que esperar a que el otro obtenga su frame.