# CLM-8B en casa: el competidor abierto de jev, medido con nuestros exámenes

28 de septiembre de 2026. CLM-8B (Stanford + NVIDIA, Apache 2.0, publicado el 23-09-2026) anuncia hasta 9× menos latencia que jev y resultados "a la par" sin entrenar.

## Cómo funciona

- **Un *bi-encoder*:** Qwen3-8B congelado da un vector por texto (el del último token). Dos cabezas pequeñas (~20 M parámetros cada una, 76 MB) proyectan por un lado la situación con la pregunta y por otro cada opción. La probabilidad de cada opción es el softmax de escala × coseno.
- **Por qué es rápido:** los vectores de las opciones se calculan una vez y se guardan.
- **Preguntas:** las mismas que jev (sí/no, elegir, nota) y además ordenar candidatos.

## Montaje en una RTX 2070 (8 GB), sin vLLM ni WSL

- **Compresión:** Qwen3-8B a **4 bits** (bitsandbytes nf4, cálculo en fp16) ocupa 4,9 GB de la gráfica; en bf16 serían ~16 GB.
- **Lo demás, como el original:** las cabezas oficiales y las plantillas de texto del repositorio. Código en `clm/local.py` (motor) y `clm/bench.py` (exámenes).
- **Comprobación con el ejemplo del README:**

| | Original (bf16) | Nuestro montaje (4 bits) |
|---|---|---|
| Departamento "billing" | 0,939 | 0,918 |
| Frustración (0-2) | 1,98 | 2,00 |
| Mareas → "gravedad de la Luna" | 0,997 | 0,983 |
| ¿Urgente? (sí/no) | 0,41 | **0,88** |

Coincide en elegir y puntuar. En la pregunta de sí/no la compresión se nota.

## Resultados (sin entrenar, mismos exámenes que jev y Laya)

| | CLM-8B | Laya sin entrenar | Laya destilada | Referencia tonta |
|---|---|---|---|---|
| Comecocos: misma salida que jev (300 cruces) | **40 %** | 48 % | 92,3 % | azar ≈ 42 % |
| Comecocos con un rival cerca (31) | 35 % | — | 97 % | — |
| Bluesky: emoción como jev (600 posts) | **28,7 %** | 48,5 % | 65,2 % | siempre "neutral": 29 % |
| Bluesky: tema como jev (600 posts) | **29 %** | 38,8 % | 65,5 % | siempre "vida diaria": 32 % |
| Tiempo por decisión en la RTX 2070 | 690 ms (comecocos), 164 ms (post, 2 preguntas) | 60-100 ms | 60-100 ms | — |

- **En nuestras tareas, CLM sin entrenar queda al nivel del azar.** No es el idioma: en los posts en inglés acierta un 27 %, igual que en el resto. Reparte sus respuestas casi al azar entre las emociones.
- **El comecocos le va especialmente mal por diseño.** Las salidas solo se distinguen por números ("rival a 3 casillas", "12 casillas de huida"), y un *bi-encoder* convierte cada opción en vector sin ver las demás. No puede comparar números entre opciones; jev y Laya leen situación y opción juntas.
- **La velocidad anunciada (16,5 ms) no aparece aquí.** En una 2070 con el codificador comprimido, cada estado de ~1.000 tokens cuesta ~700 ms. El guardado de opciones solo ayuda cuando las opciones se repiten (en Bluesky sí, en el comecocos no).

## Afinado con las etiquetas de jev en Bluesky (28 de septiembre)

Receta como la de Laya: los mismos 6.118 posts de entrenamiento y el mismo examen de 600 posts. Se entrenan solo las dos cabezas, partiendo de las oficiales, para imitar las probabilidades de jev (objetivo suave). Script: `clm/finetune_bluesky.py`; cabezas nuevas en `models/clm/CLM_bluesky.pt`.

- **Vectorizar los posts con Qwen3-8B:** 6.718 posts × 2 preguntas en ~10 minutos, una sola vez.
- **Entrenar las cabezas:** segundos, porque solo son dos redes pequeñas sobre vectores ya calculados.
- **Ajuste elegido en una validación aparte** (posts 600-1.199), no en el examen: velocidad 1e-3 y 20 épocas.

| Bluesky, coincidencia con jev (600 posts) | Emoción | Tema |
|---|---|---|
| CLM-8B sin afinar | 28,7 % | 29,0 % |
| **CLM-8B afinado** | **62,5 %** | **69,8 %** |
| Laya destilada (mismos datos) | 65,2 % | 65,5 % |
| Laya sin entrenar | 48,5 % | 38,8 % |

- **Afinado, CLM empata con Laya destilada:** −2,7 puntos en emoción y +4,3 en tema, con un ruido del examen de unos ±4.
- **Entrenar es muchísimo más rápido:** segundos frente a 8,5 minutos, porque el codificador no se toca.
- **Usarlo sale mucho más caro:** 164 ms por post en la 2070 frente a ~2 ms por decisión de Laya en lotes, y 4,9 GB de gráfica frente a ~1,5.
- **Lectura:** lo que sabía CLM de fábrica apenas servía para esta tarea. Lo que funciona es la receta de siempre, un profesor que etiqueta y un alumno que se afina, y con ella casi cualquier alumno razonable llega al mismo sitio (~65 %). El techo lo pone el profesor, no la marca del alumno.

## Donde debería brillar: elegir entre los 8.131 municipios de una vez (28 de septiembre)

Es su terreno sobre el papel: muchísimas opciones que se guardan una vez, y que se distinguen por el significado y no por cifras. jev llega a 255 opciones y Laya a ~20; el reranker del mapa lee 100 candidatos. Script: `clm/finetune_mapa.py`.

- **Vectorizar:** 8.131 fichas (sin el nombre del pueblo) y 5.003 frases del profesor, ~15 min una sola vez.
- **Afinar:** las cabezas aprenden a acercar cada frase a los pueblos que eligió el profesor (según su nota) y a alejarla de los otros 8.131. 75 s. Ajuste elegido con 300 frases de validación (velocidad 1e-2, 30 épocas).
- **Velocidad:** **134 ms por búsqueda contra los 8.131 municipios** en la 2070. Es lo que ninguno de los otros puede hacer de una sola vez.

| Acierto en los 10 primeros (juez `gpt-6-luna`, 50 frases del examen) | |
|---|---|
| CLM sin afinar, entre los 8.131 | 5 % |
| **CLM afinado, entre los 8.131** | **29 %** |
| Buscador de palabras solo | 36,8 % |
| Buscador por significado (bge-m3) solo, pasada anterior | 24,8 % |
| Palabras → reranker afinado | 61,4 % |
| CLM → reranker afinado | 51,8 % (−9,6, IC de −16,6 a −2,8) |
| **Palabras + CLM → reranker afinado** | **62,8 %** (+1,4, IC de −1,6 a +5,0: empate) |

- **Tampoco aquí brilla.** Afinado, elige entre los 8.131 mejor que el buscador por significado de serie (29 % frente a 24,8 %), pero peor que el de palabras (36,8 %). Como primer paso para el reranker queda claramente por debajo; mezclado con el de palabras, empata con lo mejor que teníamos.
- **Ejemplos:**
  - Bien: "ruta de vinos y bodegas" da Badarán (Rioja), "playa con dunas" da Valdoviño y "montaña con nieve" da Valdelinares.
  - Rarezas con mucha seguridad: "comer pulpo y marisco" da Chert (58 %) y "estrellas desde un castillo" da Chañe (14 %).
- **Por qué:** el examen favorece al buscador de palabras (sus frases salieron de las fichas), y las etiquetas del profesor solo cubren los 50 candidatos que trajo ese buscador. CLM aprende de pocos positivos y trata como negativos pueblos buenos que nadie miró.
- **Conclusión práctica:** en esta 2070, bge-m3 (568 M, 27 ms, sin afinar) hace el mismo papel de preselección casi igual y mucho más barato. CLM no aporta nada que no tuviéramos.

## Cautelas

- **La compresión:** las cabezas se entrenaron con Qwen3-8B sin comprimir, y la de 4 bits cambia algo los vectores (se ve en el sí/no). No podemos descartar que en bf16 saque más, pero no cabe en 8 GB.
- **Sus tareas no son las nuestras:** sus pruebas son uso de ordenador, llamadas a herramientas y WikiRacing, con opciones que se distinguen por su significado, no por cifras. Sus mejores números (DeepSWE, Terminal-Bench) son **afinando las cabezas**, no sin entrenar.
- **Lo que queda por probar:** afinarlo también en el comecocos. Serían horas de vectorizar (29.000 estados de ~1.000 tokens), y el *bi-encoder* seguiría sin comparar cifras entre opciones.

## Conclusión

Es la misma lección que con Laya, con otro modelo: **sin entrenar, los "System One" abiertos no sustituyen a jev en tareas concretas**, y la velocidad anunciada depende del hardware y de que las opciones se repitan. Y el mismo patrón del mapa: un *bi-encoder* va muy bien para preseleccionar entre miles de opciones guardadas, pero para decidir hace falta leer situación y opción juntas.
