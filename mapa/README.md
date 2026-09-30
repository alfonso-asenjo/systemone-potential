# Luces de España

Escribes lo que buscas ("pueblo tranquilo con playa y surf") y el mapa de España se enciende
donde [jev](https://typesafe.ai/) cree que está, mientras escribes. No enseña solo la
respuesta: enseña **toda la distribución de probabilidad**, como luces de ciudades vistas de
noche. Con una frase vaga el calor se reparte por media costa; al añadir "surf" se va de
golpe al Cantábrico.

## Arrancar

```bash
python mapa/server.py          # y abrir http://127.0.0.1:8780/
```

La clave de jev sale del `.env` del repositorio (`JEV_PROVIDER`, `OPENROUTER_API_KEY`) y el
navegador nunca la ve. Con `?demo` en la URL la página escribe sola los ejemplos, letra a
letra, para grabar vídeo sin tocar nada.

## Cómo funciona

- **255 lugares**, el máximo de opciones de un Choice de jev. Cada uno va descrito por lo que
  lo distingue: provincia, costa o interior, habitantes, cómo se llega desde Madrid y sus
  rasgos ("ola izquierda de surf famosa, ría de Urdaibai, pueblo tranquilo"). Es la lección
  del comecocos: sin datos propios en cada opción, jev no tiene con qué separarlas.
- **Una llamada por frase**, con 170 ms de espera desde la última tecla. Solo hay una
  pregunta en vuelo por conexión: si escribes mientras tanto, se contesta la última frase.
- **El código filtra antes de preguntar** lo que jev no hace bien. En la prueba inicial,
  con "a menos de 3 horas de Madrid" siguió poniendo primero Mundaka, que está a 4 y media.
  Ahora `questions.py` lee "a menos de N horas", "N horas como mucho", "hora y media" y
  "sin avión" o "en coche", apaga en gris los lugares que no cumplen y a jev solo le llegan
  los que quedan. El panel enseña qué ha filtrado el código.
- **Cuánto duda jev**: el número efectivo de opciones, e elevado a la entropía de la
  distribución. 1 es certeza; 255, no saber nada.

## Datos

`data/places.txt` es la única fuente escrita a mano: nombre, municipio, provincia, costa,
habitantes aproximados y rasgos. `build_places.py` la convierte en `static/places.json`:

- **Coordenadas**: centroide del municipio en [es-atlas](https://github.com/martgnz/es-atlas),
  los límites municipales del Instituto Geográfico Nacional. Comprobadas a mano San
  Sebastián, Sevilla y Toledo.
- **Horas desde Madrid**: distancia en línea recta × 1,25 a 100 km/h, redondeada a la media
  hora. Aproximadas y así lo dicen (San Sebastián 4,5 h, Sevilla 5 h, Toledo 1 h).
- **Islas, Ceuta y Melilla**: sin horas; su descripción dice que hay que ir en avión o barco.

Los habitantes y los rasgos los escribí yo y están sin cotejar con el INE. Antes de publicar
conviene revisarlos, porque en un mapa de España los errores se notan.

```bash
python mapa/build_places.py    # tras tocar data/places.txt
```

## Medido

| Frase | Primero | Números efectivos |
|---|---|---|
| pueblo tranquilo con playa | Mundaka 16 %, Calella, Cabo de Gata… | 11 |
| … y surf | Mundaka 77-93 % | 1,4 |
| ver las estrellas | Santa Cruz de La Palma 81 % | – |
| comer marisco | A Coruña 39 %, O Grove 19 % | 8,8 |
| fiesta | Pamplona 49 %, Ibiza 32 % | 3,6 |
| sitio romántico para pedir matrimonio | Deià, Albarracín… y Teruel, por los Amantes | 19 |

Con las 255 opciones: de 370 a 650 ms por llamada, unos 16.000 tokens de entrada y
0,0007 dólares por llamada. Con filtros la llamada es más corta y más barata.

## Ficheros

```
server.py          aiohttp: sirve la página, filtra, pregunta a jev, graba cada respuesta
questions.py       la pregunta, la descripción de cada lugar y los filtros del código
build_places.py    data/places.txt + municipios del IGN -> static/places.json
data/places.txt    los 255 lugares, escritos a mano
static/
  index.html, style.css, map.js    la página
  places.json                       generado
  vendor/                           d3, topojson-client, d3-composite-projections y
                                    las provincias de es-atlas, para que funcione sin red
logs/              una grabación por conexión, en JSONL
```
