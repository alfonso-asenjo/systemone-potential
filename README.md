# systemone-potential

Demos de una IA que **decide** en vez de escribir: los modelos «System One». No redactan
respuestas; reciben una situación y devuelven una decisión tipada (sí/no, una opción de una
lista o una nota en una escala) con su probabilidad, en una sola pasada.

Aquí se prueban dos: [jev](https://typesafe.ai/), de TypeSafe, que se usa por API, y
[Laya](https://huggingface.co/convaiinnovations/laya-multilingual), una alternativa abierta
que corre gratis en una tarjeta gráfica de casa. El hilo de todo el repositorio es pasar de
alquilar la decisión (jev) a tenerla (un modelo propio entrenado con lo que decide jev), con
los números medidos en cada paso.

## Las demos

| Demo | Carpeta | Quién decide | Cómo se arranca |
|---|---|---|---|
| **StarCraft II**: la IA manda, el código ejecuta | `jevcraft/`, `run.py` | jev | `python run.py` (ver abajo) |
| **La Roja en el laberinto**: un comecocos con los rivales del Mundial 2026 | [`pacman/`](pacman/README.md) | jev, o Laya entrenada con sus decisiones | `python pacman/server.py` → http://127.0.0.1:8770/ |
| **Luces de España**: 255 lugares que se encienden mientras escribes | [`mapa/`](mapa/README.md) | jev | `python mapa/server.py` → http://127.0.0.1:8780/ |
| **Luces de España y mapa de carreteras**: los 8.131 municipios | `mapa/big_*.py`, `mapa/static_big/` | bge-reranker afinado con las etiquetas de un profesor (o Laya) | `.venv-laya/Scripts/python mapa/big_server.py` → http://127.0.0.1:8781/ y `/carreteras.html` |
| **La casa de internet**: Bluesky en directo | `bluesky/` | Laya entrenada con las etiquetas de jev | `.venv-laya/Scripts/python bluesky/server.py` → http://127.0.0.1:8790/casa.html |

La casa también funciona sin servidor ni modelo: `bluesky/static/casa.html?grabacion`
reproduce en bucle una grabación de casi 9 minutos (`bluesky/static/grabacion.json`, hecha
con `bluesky/record.py`) que guarda solo la emoción y el tema de cada post, nunca su texto ni
su autor. El comecocos tiene lo mismo con sus partidas grabadas (`?replay=<partida>` y
`pacman/build_single.py`). Los mapas, con `?grabacion`, responden a sus búsquedas de
ejemplo con las respuestas guardadas por `mapa/grabar.py`.

## Resultados y diarios

- [`docs/laya-vs-jev.md`](docs/laya-vs-jev.md): Laya sin entrenar frente a jev, y cómo el
  alumno llegó a empatar con el profesor en el comecocos (6 de 20 partidas frente a 5 de 20).
- [`docs/mapa-8000-diario.md`](docs/mapa-8000-diario.md): el mapa de 8.131 municipios, con
  exámenes a ciegas, el reordenador afinado y el concurso de profesores
  (`docs/concurso-*.csv`).
- [`docs/clm-8b.md`](docs/clm-8b.md): la prueba de CLM-8B (Stanford y NVIDIA), descartado.
- `pacman/distill/`: la destilación de jev en Laya.

## Instalación

Dos entornos:

- **jev y StarCraft II**: `pip install -r requirements.txt`.
- **Laya y los modelos locales**: ver la cabecera de [`requirements-laya.txt`](requirements-laya.txt).
  Probado en Windows con una RTX 2070 de 8 GB.

Claves: copia `.env.example` a `.env` y rellena las que uses. jev sirve por cualquiera de estos
proveedores, con la misma API:

- `JEV_PROVIDER=openrouter` + `OPENROUTER_API_KEY` (sin lista de espera, unos 0,04 € por millón de tokens)
- `JEV_PROVIDER=cloudflare` + `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN`
- `JEV_PROVIDER=typesafe` + `TYPESAFE_API_KEY`

Los scripts del mapa usan además `OPENAI_API_KEY` (el profesor, gpt-6-luna) y `WIKI_CONTACT`
(un correo o web de contacto, que Wikipedia pide en sus descargas).

## Lo que no está en el repositorio

Por tamaño o porque no se puede publicar, y cómo se regenera:

| Qué | Cómo se consigue |
|---|---|
| `models/` (11 GB) | Laya base desde Hugging Face ([multilingual](https://huggingface.co/convaiinnovations/laya-multilingual), [typed-decisions](https://huggingface.co/convaiinnovations/laya-typed-decisions)) y `BAAI/bge-reranker-v2-m3` y `BAAI/bge-m3`. Los alumnos se entrenan con `pacman/distill/train.py`, `bluesky/train.py`, `mapa/big_rerank.py` y `mapa/big_bge_train.py` |
| `mapa/data/` (313 MB) | Los scripts `mapa/big_*.py`, en el orden de [`docs/mapa-8000-diario.md`](docs/mapa-8000-diario.md): Wikipedia y Wikidata, descripciones y etiquetas de gpt-6-luna (unos 3 €). La web ya lleva lo que necesita en `mapa/static_big/` |
| Posts de Bluesky | Son de otras personas. Se capturan con `bluesky/spike/capture.py` y los etiqueta jev con `bluesky/label.py` (unos 0,19 € por 6.700 posts) |
| Decisiones de jev en el comecocos | Se sacan de tus propias partidas con `pacman/distill/dataset.py` |
| Registros de partidas y servidores | Llevan IPs y rutas del ordenador donde se ejecutaron |

## StarCraft II

jev hace de general: cada ~1,5 s recibe el estado de la partida en JSON y contesta en una
llamada el foco de la economía (Choice), qué hace el ejército (Choice), cuánta amenaza hay
(Score de 0 a 3), si el rival prepara un ataque temprano y si vamos por delante (Noul). Un bot
Protoss de [python-sc2](https://github.com/BurnySc2/python-sc2) ejecuta: construye, investiga,
entrena y mueve el ejército. Si jev no está seguro de una opción, se mantiene la anterior, y un
panel web enseña el estado, las probabilidades, la latencia y el coste.

Hace falta StarCraft II (gratis en Battle.net) con los mapas `Ladder2019Season3` en
`StarCraft II/Maps/`.

```bash
python offline_test.py                 # una llamada a jev con un estado grabado, sin juego
python run.py                          # partida en tiempo real contra la IA; panel en http://127.0.0.1:8765
python run.py --difficulty Hard --enemy zerg
python run.py --no-jev --fast          # modo reglas: prueba el bot sin llamar a la API
python run.py --skip 240 --time-limit 900 --difficulty Hard --window 2560x1440
                                       # 4 min rápidos con reglas y luego jev en tiempo real (para vídeo)
python replay.py logs/sc2-XXXX.jsonl   # repite en el panel las decisiones de una partida grabada
python highlights.py logs/sc2-XXXX.jsonl   # los momentos para cortar el vídeo
```

`--chat` escribe cada cambio de decisión en el chat del juego. Va apagado por defecto porque una
vez cerró StarCraft II al enviar la primera línea.

## Datos de terceros y licencias

- **Descripciones de los municipios** (`mapa/static_big/carreteras-lugares.json`,
  `mapa/static_big/places.json`): escritas por gpt-6-luna a partir de Wikipedia en español, así
  que se publican bajo [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.es).
- **Cartografía**: [IGN](https://www.ign.es/) (términos municipales y el Mapa Topográfico
  Nacional por WMTS, CC BY 4.0) y [Natural Earth](https://www.naturalearthdata.com/) (dominio
  público). Coordenadas de [Wikidata](https://www.wikidata.org/) (CC0). Las fotos de los
  pueblos se cargan al vuelo desde Wikimedia Commons, cada una con su autor y su licencia.
- **Librerías incluidas** en `mapa/static/vendor/`: d3, topojson-client y
  d3-composite-projections, cada una con su aviso de copyright en la cabecera.
- **`clm/schema.py`**: tomado de CLM-8B, Apache 2.0 (`clm/LICENSE-CLM`).

## Licencia

El código de este repositorio se publica bajo la licencia [Apache 2.0](LICENSE). Los datos y las
librerías de terceros mantienen sus propias licencias, detalladas en el apartado anterior.
