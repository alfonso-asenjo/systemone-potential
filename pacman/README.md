# La Roja en el laberinto

España recorre un laberinto perseguida por los ocho rivales a los que se enfrentó en el
Mundial de 2026, cada uno con su bandera. Quien decide hacia dónde va es
[jev](https://typesafe.ai/), un modelo de decisión que no escribe texto: recibe el estado
del juego y devuelve una acción tipada con probabilidades calibradas, en unos 300 ms.

Las píldoras de poder son el trofeo. Al comerse a un rival, el marcador enseña el
resultado real de aquel partido.

| Nivel | Rivales | Partidos |
|---|---|---|
| 1, fase de grupos y dieciseisavos | Uruguay, Austria, Arabia Saudí, Cabo Verde | 1-0, 3-0, 4-0, 0-0 |
| 2, camino a la final | Argentina, Francia, Bélgica, Portugal | 1-0 en la prórroga, 2-0, 2-1, 1-0 |

## Arrancar

```bash
pip install -r ../requirements.txt      # aiohttp y python-dotenv
python server.py                        # y abrir http://127.0.0.1:8770/
```

La clave de jev sale del `.env` del repositorio padre (`JEV_PROVIDER`, `OPENROUTER_API_KEY`).
El navegador nunca la ve: el juego corre en el navegador y el servidor es quien pregunta.

Para verlo desde el móvil en la misma red:

```bash
python server.py --host 0.0.0.0
```

Al arrancar imprime las direcciones que sirven desde otro dispositivo, del tipo
`http://192.168.1.x:8770/`. Mientras esté así, el juego es accesible para cualquiera en
esa red; con `--host 127.0.0.1`, que es lo que hace por defecto, solo desde este ordenador.
El diseño se adapta a ancho de móvil y la partida se juega sola, así que no hace falta
teclado.

Parámetros de la URL: `?seed=1234` fija la partida, `?speed=2.6` cambia la velocidad de
España, `?replay=pacman-XXXX.jsonl` reproduce una partida grabada sin gastar API.

Teclado: flechas o WASD toman el control, `J` se lo devuelve a jev, espacio pausa, `R` reinicia.

## Qué se le pregunta a jev

Una sola llamada por casilla, con cinco preguntas evaluadas a la vez:

- **dirección**, un Choice entre las salidas hacia delante, nunca entre paredes y nunca
  hacia atrás.
- **peligro**, un Score de 0 a 3.
- **a por el trofeo**, **a cazar** y **dar la vuelta**, tres Noul.

El estado que recibe lleva calculado todo lo que el código sabe calcular: distancias en
casillas por búsqueda en anchura, píldoras al alcance de cada salida, qué rivales se están
acercando y, sobre todo, el **sitio para escapar** de cada salida. jev solo pone el juicio.

### El sitio para escapar

`escape_room`, en `static/jev.js`. Para cada salida, cuántas casillas puede correr España por
ahí, a través de todos los cruces que haga falta, sin que ningún rival activo pueda llegar
antes que ella a ninguna de ellas. Se cuenta hasta 12, que significa campo abierto; menos es
una trampa, y el número dice cuánto aguanta antes de que la corten.

- Cada rival se modela con una búsqueda en anchura desde su casilla, sin poder dar la vuelta
  en el primer paso, a su velocidad (1,6 casillas por segundo; España va a 2,2).
- España tiene que llegar a cada casilla al menos **0,6 s** antes que el rival. Chocan
  cuando sus centros están a 0,55 casillas, y cruzarse de frente pide 0,55/2,2 + 0,55/1,6 s.
  Con 0,3 s moría en cruces en los que un rival entraba a la vez.
- Se comprueba primero la **casilla por la que se pregunta**, el cruce al que está a punto
  de entrar: si un rival llega a él con ella, todas sus salidas valen 0.
- Se cuenta un paso más para España, porque cuando se hace la pregunta todavía le falta
  una casilla para llegar.

Antes hubo una versión más simple, `escape_margin`: casillas de ventaja al siguiente cruce.
Veía las trampas de un pasillo, pero no que todas las salidas del cruce siguiente
estuvieran ya cortadas, y así moría España cuando la cerraban cuatro rivales.

### Guardas

Todas están en `decide.py` salvo la última, y todas se ven en el panel:

- **umbral de confianza** (0,25): por debajo decide la regla de seguridad, que toma la
  salida con más sitio para escapar y, a igualdad, la de rival más lejano.
- **listón para volver** (0,28): dar la vuelta no compite con seguir adelante dentro del
  Choice, es un juicio aparte y tiene que superar su propio listón, calibrado sobre lo que
  de verdad contesta jev y no sobre lo que parecería alto.
- **veto a volver hacia una trampa** (`vetoed`): si jev pide volver pero detrás hay menos de
  12 de sitio y delante hay más, España sigue adelante. Medido: jev pidió volver dos veces
  seguidas en el túnel, con campo abierto delante, y la llevó contra Uruguay.
- **vuelta forzada** (`forced`): si delante hay trampa, un rival a 3 casillas o menos y
  detrás al menos 3 casillas más de sitio, España vuelve aunque jev no lo pida.
- **tiempo entre vueltas** (4 casillas, en `static/jev.js`): el navegador ignora una vuelta
  si España acaba de dar otra, y entonces sigue por la salida `forward` que manda el
  servidor. Una **huida** (`escape`: trampa delante y más sitio detrás) no espera: ese
  tiempo le bloqueó 5 de las 9 veces que jev acertó a salir de una trampa.

## Estado a 23 de septiembre de 2026

Medido con `tests/play.mjs`, partidas enteras con jev en tiempo real:

| Versión | Partidas | Gana | Hasta dónde llega |
|---|---|---|---|
| Solo distancias al rival (22 y 23 sep, en el navegador) | unas 8 | 0 | la mejor, a 10 bolitas del nivel 1 |
| + `escape_room` a 12 casillas | 6 | 1 | una gana; tres mueren a 7, 15 y 17 bolitas del nivel 1 |
| + cruce propio, holgura 0,6 s, veto | 2 | 1 | las dos pasan el nivel 1 |

Las muertes que quedan son encerronas: dos o tres rivales la cierran en una esquina, sobre
todo abajo a la izquierda, y todas las salidas llevan varias preguntas seguidas marcando 0 o
1 de sitio. Ya no son despistes de una casilla. Siguientes pasos posibles:

1. **Ver la encerrona venir antes**: que el sitio para escapar tenga en cuenta que los
   rivales van a por la posición de España y no se quedan quietos en su camino. Una salida
   que marca 12 puede caer a 6 en una sola casilla, porque un rival gira hacia ella.
2. **Equilibrar**: rivales a 1,5 casillas por segundo en vez de 1,6. Es una línea en
   `static/ghosts.js`, y habría que volver a medir.

Coste medido: unos 0,06 dólares por partida completa, de 600 a 700 decisiones.

## Pruebas

```bash
python -m pytest tests            # el laberinto: dimensiones, simetría, conectividad
node tests/sim.mjs                # el juego entero sin navegador ni jev
node tests/replay.mjs             # una grabación reproduce la misma partida
node tests/escape.mjs             # el sitio para escapar, con rivales colocados a mano
node tests/play.mjs --minutes 8   # una partida entera con jev, sin navegador y en tiempo real
python tests/shot.py --seconds 40 --out shot.png    # captura real con jev decidiendo
```

Para medir cuánto gana, `tests/play.mjs` y no `tests/shot.py`: el navegador headless frena
la animación y en una prueba de 10 minutos el reloj del juego avanzó 16 segundos. `play.mjs`
mueve el mismo juego con un temporizador normal contra el servidor de verdad; con `--debug`
enseña dónde estaban los rivales en cada muerte.

`tests/shot.py` maneja un navegador por el protocolo de devtools. Hace falta porque una
captura normal en modo headless adelanta el reloj y la partida termina antes de que jev
pueda contestar nada.

## Cómo fue construido

**Fase 1, andamiaje.** El laberinto vive en `static/maze.txt` y lo leen tanto el juego como
las pruebas. La primera prueba encontró el primer fallo: los fantasmas no podían salir de
casa porque el flood de la prueba no incluía la puerta.

**Fase 2, el juego.** Paso fijo de 1/60 s, todo determinista a partir de una semilla. La
única aleatoriedad es hacia dónde gira un rival asustado.

**Fase 3, jev al mando.** Tres cosas cambiaron respecto al plan, las tres por medir:

- *Las opciones necesitan datos propios.* Con las salidas descritas como "ve a la izquierda"
  y "ve a la derecha", jev contestaba con un 4 % de confianza: desde el texto de las
  opciones no había nada que las distinguiera. Ahora cada salida lleva sus números, y la
  confianza mediana subió al 69 %, con picos del 90 %.
- *Siempre se pregunta por la casilla a la que entra*, nunca por la que pisa. Preguntar por
  la casilla actual hacía que 21 de 32 respuestas llegaran tarde, porque España la
  abandonaba antes de que contestara.
- *Velocidad 2,2 casillas por segundo en vez de 2,5.* Medidas: latencia mediana 300 ms,
  percentil 90 en 393 ms. A 2,5 una casilla dura 400 ms y el 10 % de las respuestas no
  llegaba; a 2,2 dura 455 ms y no llega tarde el 2 %. El plan pedía exactamente este
  ajuste si se pasaba del 10 %.

Cadencia medida: 2,5 decisiones por segundo de juego, unos 1.100 tokens por llamada,
alrededor de 0,005 dólares por minuto.

**Fase 4, repetición.** Una partida grabada se reproduce con la misma puntuación en el
navegador y en Node. Comprobado en las tres direcciones sobre la misma grabación.

**Fase 5, pulido.** Las flechas de probabilidad solo se dibujan en los cruces: en un pasillo
las opciones son seguir o darse la vuelta, y la flecha de darse la vuelta queda tapada por
España. La casa de los rivales se dibuja como un banquillo, porque pintada como césped
desaparecía dentro del túnel.

Dos fallos que valieron el rato de buscarlos: los rivales comidos se quedaban atrapados en
casa rebotando entre dos casillas, porque dentro de la casa apuntaban a su esquina en vez
de a la puerta; y el atributo `hidden` no hacía nada, porque las reglas de `display` de las
clases lo pisaban, así que el telón de fin de partida tapaba la pantalla desde el principio.

**Fase 6, publicación.** Una partida grabada se empaqueta de dos formas:

```bash
python build.py            # dist/, ficheros sueltos para cualquier hosting estático
python build.py --serve    # y servirlo en 8771 para comprobarlo
python build_single.py     # dist-single/roja.html, un solo fichero de 805 kB
python build_single.py --body-only --out dist-single/roja-embebida.html
```

El fichero único lleva dentro el laberinto, las nueve banderas en data URI y las 288
decisiones de la partida. No descarga nada salvo la tipografía, así que funciona abierto
desde el disco o en un sitio que bloquee recursos externos. Es lo que se publicó.

En modo repetición el teclado no puede mover a España, porque desviarla sacaría la partida
de la grabación. Espacio pausa y R vuelve a empezar.

**Fase 7, las medias vueltas.** España iba y venía: el 23 % de las decisiones eran medias
vueltas, casi todas con mucha confianza, porque volver era una salida más del Choice y
competía de tú a tú con seguir adelante sin que nada reflejara lo que cuesta deshacer
camino. Volver pasó a ser un Noul aparte con su propio listón, y ahí apareció lo
interesante:

- *El listón hay que medirlo, no elegirlo.* Puesto a ojo en 0,70, no se alcanzó ni una vez.
  En 291 decisiones ese Noul se movió entre 0,10 y 0,31; su escala está comprimida y nunca
  se acerca al 100 %, así que un listón "alto" en abstracto es un listón inalcanzable.
- *Lo que sí sirve es el orden.* Correlaciona 0,64 con el peligro y −0,39 con lo lejos que
  queda el rival de delante, y las respuestas por encima de 0,27 tenían el peligro al doble
  y una cuarta parte de píldoras por delante que las bajas. El listón está ahora en 0,28,
  que es donde de verdad empieza la cola alta de sus respuestas.
- *Medido después:* jev pide volver en el 4,7 % de las casillas (11 de 234), con peligro
  medio 1,36 frente al 1,02 de la partida entera. El navegador veta las que llegan antes de
  cuatro casillas desde la última, así que la vuelta se aplica menos veces todavía y no hay
  ni rastro del ir y venir.

El listón viaja con cada decisión desde el servidor hasta el panel, para que la marca del
panel no mienta el día que el número cambie.

Dos trampas del arnés de capturas, las dos descubiertas al colgarse una medición: pedía
siempre el puerto 9333 de depuración y se conectaba a lo que hubiera ahí, que resultó ser
un navegador olvidado por una ejecución anterior; y al terminar mataba solo el proceso que
había lanzado, dejando vivos los hijos, que es de donde salía el navegador olvidado. Ahora
lee el puerto que el navegador escribe en su propio perfil y lo mata con toda su
descendencia.

**Fase 8, que no se la coman (23 de septiembre).** Ninguna partida pasaba del nivel 1. Por
orden de descubrimiento:

- *El tiempo entre vueltas nunca funcionó.* Al ignorar una vuelta, el navegador tenía que
  seguir por la salida de delante, pero el servidor no se la mandaba y acababa usando la
  de volver. 11 de 47 vueltas ocurrieron dentro de ese tiempo, y así murió dando vueltas
  entre dos casillas con 10 bolitas por comer. Ahora el servidor manda `forward`.
- *Trampas en los pasillos.* Con la distancia al rival más cercano, un rival esperando al
  fondo de un pasillo largo parece igual de lejos que uno al otro lado de una pared. Primero
  `escape_margin`, luego `escape_room`: con él jev no eligió ni una vez la salida con menos
  sitio cuando había otra mejor (0 de 35 cruces en los que podía equivocarse).
- *El juicio de volver es bueno.* Con trampa delante y camino libre detrás, jev pidió volver
  en 9 de 11 casos y nunca hacia una trampa. Lo que fallaba era el tiempo entre vueltas,
  que bloqueaba las huidas. Una vez, en el túnel, sí pidió volver hacia un rival: de ahí
  el veto.
- *Caché del navegador.* Una partida entera se jugó con un `jev.js` viejo, sin el sitio
  para escapar, y España fue de frente contra un rival. El servidor manda ahora
  `Cache-Control: no-cache` en todo.
- *El navegador headless no sirve para medir.* Frena `requestAnimationFrame` aunque se le
  pasen las opciones contra el frenado: en 10 minutos reales el reloj del juego avanzó
  16 segundos. De ahí `tests/play.mjs`, el mismo juego en Node con un temporizador normal.
- *Logs pisados.* Dos partidas que empezaban en el mismo segundo escribían en el mismo
  fichero. Ahora el segundo lleva el sufijo `-2`.

## Ficheros

```
server.py        aiohttp: sirve el juego, pregunta a jev, graba cada decisión
questions.py     las cinco preguntas, con los datos de cada salida en sus criterios
decide.py        umbral, listón, veto, vuelta forzada, huida y regla de seguridad
static/
  maze.txt       el laberinto, fuente única para el juego y las pruebas
  maze.js        parseo, túnel, cruces, distancias
  game.js        bucle de paso fijo, España, colisiones, vidas, niveles
  ghosts.js      los ocho rivales, sus personalidades y la casa
  render.js      el campo, las banderas, las flechas de decisión
  jev.js         cuándo preguntar, qué estado enviar (sitio para escapar incluido),
                 qué hacer con la respuesta
  panel.js       el panel y el marcador
  main.js        arranque y bucle de fotogramas
tests/           laberinto, simulación, repetición, sitio para escapar, partidas en Node
logs/            una grabación por partida, en JSONL
```

El nombre y los gráficos son propios. No se usa nada de Pac-Man.
Las banderas son de [flag-icons](https://github.com/lipis/flag-icons), licencia MIT.
