# Diario: Luces de España con los 8.131 municipios

Del 24 al 26 de septiembre de 2026.

## Resumen

- Todos los municipios de España están descritos a partir de fuentes y organizados en un árbol.
- Hay 5.003 búsquedas etiquetadas por un profesor barato (`gpt-6-luna`).
- Un examen a ciegas hecho por una persona confirma que el profesor elige bien: 97 % de aciertos, frente al 53 % de un buscador de palabras.
- Laya como árbol de decisiones (comunidad, provincia, grupo, municipio) **no supera al buscador**: 23-28 % frente a 34-39 %. Cada nivel acierta un 80-84 %, pero los errores se encadenan.
- **Coste total del profesor: unos 3,6 $.**

## Lo que se hizo, en orden

| Paso | Qué | Resultado | Coste |
|---|---|---|---|
| Datos | Wikidata, consulta por provincia (la de toda España caducaba), cruzada con los polígonos del IGN | **8.131 municipios exactos**, todos con población y artículo de Wikipedia, 7.992 con altitud. De regalo, 29.805 núcleos para una versión futura | 0 |
| Fuentes | Artículo completo de Wikipedia, recortado a la introducción y las secciones de patrimonio, fiestas, gastronomía, naturaleza y turismo | Solo con la introducción, 5 de cada 8 pueblos salían "sin rasgos destacados"; con el artículo, 1 de cada 10 | 0 |
| Descripciones | `gpt-6-luna`, razonamiento `none`, solo con lo que dice la fuente | 8.131 descritas, 417 "sin rasgos" (294 de menos de 500 habitantes). Razonar en `low` no mejoraba y colaba datos administrativos | **0,81 $** |
| Datos calculados | Centro, horas desde Madrid y costa (Natural Earth 10m, margen de 1,5 km, ajustado midiendo con Santillana del Mar) | 466 municipios costeros | 0 |
| Árbol | Comunidad → provincia → [mitad] → grupo geográfico → municipio, nunca más de 20 opciones | 604 grupos. En Burgos, Salamanca, Zaragoza, Valencia, Barcelona y Navarra hace falta un nivel más | 0 |
| Descripción de nodos | `gpt-6-luna` resume los rasgos reales de los municipios de cada nodo | 687 nodos | **0,08 $** |
| Frases | `gpt-6-luna` combina 23 tipos de búsqueda, 5 estilos y los rasgos de 6 pueblos al azar como inspiración | **5.003 frases**, con una mediana de 10 palabras | **0,05 $** |
| Examen humano 1 | Marcar buenas respuestas entre 30 candidatos del buscador | Pesado: "más largo que un día sin pan". 10 frases | — |
| Piloto | El profesor contra las marcas humanas | Profesor 48 %, buscador 66 %. **Engañoso**: todo lo marcado estaba en los 10 primeros de la lista | 0,01 $ |
| Examen humano 2, a ciegas | 5 municipios del profesor y 5 del buscador, mezclados, sí o no | **Profesor 97 %, buscador 53 %**. +44 puntos ±14; gana en 16 frases, empata en 4, no pierde en ninguna | 0,01 $ |
| Etiquetas | El profesor elige hasta 15 municipios con nota de 1 a 3 entre los 50 candidatos del buscador | 5.003 frases, 11,3 elegidos por frase de media. 50 frases apartadas como examen | **2,57 $** |
| Alumno en árbol | Laya multilingüe, 8 capas de arriba, 2 pasadas, 47.852 preguntas | 76 min en la RTX 2070 | 0 |
| Examen justo | `gpt-6-luna` juzga los 10 primeros de cada sistema en las 50 frases del examen | Alumno 23 % (3 ramas por nivel) / 28 % (6 ramas); buscador 34-39 %; profesor 67-72 % | 0,04 $ |

## Lecciones

1. **Las fuentes importan más que el modelo.** La misma IA pasó de describir bien 3 de cada 8 pueblos a 9 de cada 10 solo con darle el artículo completo en vez de la introducción.
2. **Examinar a ciegas cambia la conclusión.** Con la lista ordenada por el buscador, el profesor "perdía" 48-66. A ciegas ganaba 97-53. Una persona marca lo primero que ve, y eso es lo que pone arriba quien ordena la lista.
3. **Marcar a mano no escala; decir sí o no, sí.** Del primer examen salieron 10 frases en una tarde, y el segundo fue cuestión de minutos.
4. **El profesor es lo barato.** Todo el trabajo de la IA grande costó unos 3,6 $. Lo caro fue el tiempo humano del examen y montar los datos.
5. **El árbol de decisiones encadena errores.** Cada paso acierta un 80-84 %, pero con 4-5 pasos queda en torno a un 40 %. Seguir más ramas no lo arregla (28 % con 6 ramas, 26 % con 10, y el triple de lento). Para búsquedas genéricas ("pueblo de montaña"), obligar a elegir primero una comunidad tampoco tiene sentido.
6. **El juez automático es más estricto que la persona:** da al profesor un 67-72 %, cuando la persona le dio un 97 %. Sirve para comparar sistemas entre sí, no para dar una cifra absoluta.

## Siguiente: buscador + Laya

El buscador preselecciona 50 candidatos y Laya los reordena, repartidos en 3 preguntas de 17 opciones más "ninguno encaja". Se entrena con las mismas etiquetas (el profesor eligió justo entre esos 50) y con 3 preguntas por frase en vez de ~10.

**Resultado (26 de septiembre):** entrenado con 4.953 frases (14.696 preguntas), 3 pasadas, 38 minutos en la RTX 2070. El primer intento se cortó por falta de memoria; con 8,7 GB libres fue bien. Modelo en `models/laya-rerank`.

| Examen justo (juez `gpt-6-luna`, 50 frases) | Acierto en los 10 primeros |
|---|---|
| Laya sin entrenar reordenando los 50 | 29 % |
| Buscador de palabras solo | 36-37 % |
| **Buscador + Laya entrenada** | **43-45 %** (3 pasadas: 44,6 / 45,4 / 43,4) |
| Laya en árbol (para comparar) | 23-28 % |
| Profesor `gpt-6-luna` | 70-74 % |

- **Laya supera al buscador** en 7-8 puntos, de forma constante en las tres pasadas; el ruido del juez ronda los ±5. Y lo hace gratis y en local, en ~230 ms por búsqueda.
- **Queda lejos del profesor:** recupera en torno a un 20-25 % del hueco entre buscador y profesor. Con 300 frases ya llegaba al 39 %, así que más datos probablemente ayudarían, aunque cada vez menos.
- **Juez independiente (Claude, a ciegas, 50 frases y 943 municipios):** alumno **61 %**, buscador **48 %**, profesor **85 %**. El alumno gana al buscador por **+13 puntos ±7** (95 %): gana en 26 frases, pierde en 8 y empata en 16. El orden coincide con el del juez `gpt-6-luna` (44 / 37 / 71), así que la mejora no era un espejismo de un juez que se evalúa a sí mismo. Claude fue algo más generoso que `gpt-6-luna` en valores absolutos.
- **Calidad de datos:** en 2 de las 8.131 descripciones (El Saucejo y Collado Hermoso) se coló el razonamiento interno de `gpt-6-luna` en inglés, aun con el razonamiento en `none`. Es poco, pero hay que filtrarlo.
- **Lección:** mismas etiquetas y mismo alumno, pero dejar a Laya solo el trabajo que hace bien (elegir entre ~20) en lugar de encadenar 4-5 decisiones pasa del 23-28 % al 43-45 %. El diseño pesa más que el entrenamiento.

## Ficheros

- **Datos, en `mapa/data/big/`:** `municipios.json`, `wiki_full.jsonl`, `rasgos.jsonl`, `lugares.json`, `arbol.json`, `nodos.json`, `frases.jsonl`, `etiquetas.jsonl`, `examen*.json`, `ciego*.json`.
- **Scripts, en `mapa/`:** `big_wiki_full.py`, `big_describe.py`, `big_build.py`, `big_nodes.py`, `big_phrases.py`, `big_label.py`, `big_blind.py`, `big_tree.py`, `big_judge.py`, y la página de exámenes `review.py` con `static_review/`.
- **Modelos:** `models/laya-mapa` (el árbol) y `models/laya-rerank` (buscador + Laya). Script: `mapa/big_rerank.py`.

## El mapa (26 de septiembre)

- **Cómo arrancarlo:** `.venv-laya/Scripts/python mapa/big_server.py` y abrir http://127.0.0.1:8781/. Con `?demo`, escribe los ejemplos solo. Con `--host 0.0.0.0`, se abre a la red de casa.
- **Qué hace:** 8.131 puntos de luz (uno por municipio, más grandes cuanta más población) y halos donde encaja la frase.
- **Cerebro, todo local y a 0 € por búsqueda:**
  1. Los filtros del código de `questions.py` ("a menos de N horas", "sin avión").
  2. BM25 con índice invertido: 0-6 ms sobre los 8.131 municipios.
  3. Laya reordena los 50 candidatos: ~80 ms por búsqueda una vez caliente (la primera ~330 ms).
- **Ficheros:** `mapa/big_server.py` y `mapa/static_big/` (index.html, map.js y style.css copiados del mapa de 255 lugares; `places.json` de 633 KB).
- **Arreglos por el camino:** la descripción de El Saucejo llevaba el razonamiento colado de `gpt-6-luna` y se ha sustituido por su respuesta final. Collado Hermoso solo era larga.
- **Embudo de 100 candidatos** (decisión del 26-09): 6 bloques para Laya, **~100-125 ms** por búsqueda. La calidad frente a 50 **no está medida**. A ojo: "playa con dunas" gana La Oliva (Corralejo) y Campos (Es Trenc), y "castillos a menos de 2 h" gana Chinchón. "Pulpo y marisco" empeora (Benisa, O Carballiño) y "ver las estrellas" sigue floja.

## Un reordenador conocido, sin entrenar (27 de septiembre)

**Pregunta:** antes de destilar un modelo propio, ¿había ya un especialista que lo hiciera igual? Se probó **bge-reranker-v2-m3** (BAAI, 568 M, multilingüe), tal cual, sin entrenar nada, con las mismas 50 frases del examen y los mismos 50 candidatos del buscador que ordena Laya. Script: `mapa/big_bge.py`.

| Acierto en los 10 primeros | Juez `gpt-6-luna` | Juez Claude, a ciegas | Tiempo por búsqueda (RTX 2070, 50 candidatos) |
|---|---|---|---|
| Buscador de palabras | 36 % | 48 % | ~0 ms |
| **Laya entrenada (alumno)** | **45 %** | **61 %** | **81 ms** |
| **bge-reranker, sin entrenar** | **49 %** | **~61 %** corregido (72 % en bruto, ver abajo) | **174 ms** |
| bge-reranker con el texto recortado que ve Laya | 42 % | — | 111 ms |
| Profesor `gpt-6-luna` | 68 % | 85 % | — |

- **Juez `gpt-6-luna`:** bge supera al alumno por 4 puntos, con un IC 95 % de -0,4 a +9,2. Gana 19 frases, empata 22 y pierde 9. Con el mismo texto recortado, bge queda 3 puntos por debajo (IC de -8 a +3). **Es un empate:** la pequeña ventaja viene de leer más datos de cada municipio (provincia, altitud, costa).
- **Juez Claude:** solo se juzgaron a ciegas los 170 municipios nuevos que traía bge, mezclados con 100 ya juzgados como control (`mapa/big_claude_judge2.py`).
  - **Los controles pillaron un sesgo:** esta vez fui más generoso. Aprobé 19 de los 36 que antes había rechazado y no suspendí ninguno de los que había aprobado.
  - Ese sesgo solo infla a bge, porque sus municipios nuevos son los únicos juzgados de nuevo. En bruto salía un 72 % (+11 puntos sobre el alumno).
  - Con la tasa de cambio de los controles, los nuevos habrían tenido ~40 % de aprobados con el criterio del primer examen, no el 72 %. **Corregido, bge queda en ~61 %, empatado con el alumno.**
- **Conclusión:** un reordenador que ya existía, gratis, sin etiquetas, sin profesor y sin entrenar, **empata con nuestro alumno destilado** en esta tarea. Tiene sentido: emparejar una búsqueda con documentos es justo para lo que se entrenan los reordenadores, con millones de ejemplos.
- **Qué cambia:** la destilación no fue inútil. Cuesta 2,6 $ de etiquetas y 76 minutos, el alumno es 2 veces más rápido y la receta vale donde no hay especialista (comecocos, Bluesky). Pero **para buscar y ordenar hay que probar primero un reordenador conocido.** El siguiente paso natural sería afinar el reordenador con las etiquetas del profesor, que probablemente superaría a los dos (no está medido).
- **Coste:** juez `gpt-6-luna` 0,012 $; juez Claude, sin coste de API.
- **Ficheros:** `mapa/data/big/bge-listas.json`, `bge-report.json`, `bge-veredictos.json`, `claude2_*.json` y `claude2-report.json`. Modelo en `models/bge-reranker-v2-m3` (2,2 GB).

## El reordenador afinado con las etiquetas del profesor (27 de septiembre)

Mismas 4.900 frases de entrenamiento que Laya. Se entrenan las 8 capas de arriba (de 24) y la cabeza, 102 M parámetros; el resto queda congelado en media precisión. En cada paso ve un grupo de 32 candidatos de una frase (todos los elegidos por el profesor y el resto sin elegir) y aprende a repartir la probabilidad según las notas de 1 a 3. Son 2 pasadas, 42 minutos en la RTX 2070 y 4,5 GB de memoria. Script: `mapa/big_bge_train.py`; modelo en `models/bge-rerank-mapa`.

| Acierto en los 10 primeros | Juez `gpt-6-luna` | Claude, a ciegas | Hueco buscador-profesor recuperado |
|---|---|---|---|
| Buscador de palabras | 39 % | 48 % | — |
| Laya entrenada (alumno) | 48 % | 61 % | 31-36 % |
| bge-reranker sin entrenar | 51 % | ~61 % | — |
| **bge-reranker afinado** | **59 %** | **~77 %** | **64-78 %** |
| Profesor `gpt-6-luna` | 70 % | 85 % | — |

- **Juez `gpt-6-luna`:** el afinado supera al alumno por +10,2 puntos (IC 95 % de +6,0 a +14,6; gana 29 frases, empata 15 y pierde 6) y al reordenador sin afinar por +7,6 (IC de +3,0 a +12,4).
- **Con las métricas que proponía ChatGPT y el juez `gpt-6-luna`,** el afinado iguala al profesor en los 8 primeros. Ojo: este juez es el profesor y favorece a quien aprendió de él.

  | | Precisión en los 5 primeros | En los 8 primeros | Frases con al menos 6 de 8 buenos |
  |---|---|---|---|
  | Afinado | 67 % | 64 % | 54 % |
  | Profesor | 72 % | 64 % | 52 % |
  | Laya | 58 % | 51 % | 34 % |

- **Juez Claude (ronda 3, a ciegas):**
  - Juzgó los 109 municipios nuevos del afinado mezclados con 150 controles del primer examen.
  - Los controles coinciden en 135 de 150: 13 de 58 "no" pasaron a "sí" y 2 de 92 "sí" pasaron a "no". Hubo algo de generosidad, pero mucha menos que en la ronda 2.
  - En bruto el afinado saca 77,8 %, y corregido 76,7 %, frente al 61,4 % del alumno: **+16 puntos**. Gana 33 frases, empata 13 y pierde 4.
- **Lectura:** con el mismo profesor y las mismas etiquetas, **un alumno más grande y ya especializado en ordenar aprende el doble que Laya.** El cuello de botella era el alumno, no el profesor. Ahora sí compensa buscar un profesor mejor: hay un alumno capaz de aprovecharlo.
- **Coste:** 0 $ de entrenamiento y 0,013 $ de juez. Tarda lo mismo que el reordenador sin afinar: ~180 ms por búsqueda con 50 candidatos.

## Buscador por significado (28 de septiembre)

**Motivo:** "ver las estrellas desde un castillo" daba Lasarte-Oria, por las **estrellas Michelin** de su ficha. El buscador de palabras solo trae municipios que comparten palabras con la frase.

**Qué se montó:** bge-m3 (BAAI, multilingüe, 1,1 GB en fp16) convierte cada ficha y cada frase en un vector. Las fichas se vectorizan **sin el nombre del pueblo**; con él, "ver las estrellas" traía La Estrella y Alconchel de la Estrella. Tarda 22 s para las 8.131 fichas y unos 27 ms por frase. Los candidatos salen de mezclar las dos listas por puestos (RRF) y los ordena el reranker afinado. Script: `mapa/big_dense.py`.

| Acierto en los 10 primeros, juez `gpt-6-luna`, 50 frases | |
|---|---|
| Palabras + reranker afinado | **61,6 %** |
| Mezcla (palabras + significado) + reranker afinado | 59,8 % (−1,8, IC de −4,8 a +1,2: empate) |
| Solo significado + reranker afinado | 52,0 % |
| Solo palabras, sin reranker | 35,6 % |
| Solo significado, sin reranker | 24,8 % |

- **En el examen no mejora.** Pero esas frases las generó el profesor a partir de las propias fichas, así que comparten palabras con ellas y favorecen a BM25.
- **Con búsquedas naturales sí se nota:**
  - "ver las estrellas desde un castillo" da **Hornos**, con su planetario Cosmolarium dentro del castillo, y Miravet.
  - "cielo muy oscuro para ver la vía láctea" da **Fuencaliente de La Palma**.
- **Decisión:** el servidor usa la mezcla por defecto (`--retrieval mezcla`), unos 30 ms más por búsqueda. Pendiente: un examen con frases escritas por personas, no derivadas de las fichas.
- **Coste:** juez 0,015 $.

## Concurso de profesores (28 de septiembre)

**La pregunta:** ¿se puede conseguir un profesor mejor sin pagar ~50 $ por uno caro? Se enfrentaron 8 recetas (plan en `docs/concurso-profesores.csv`), todas con las mismas instrucciones y los mismos 50 candidatos por frase que el profesor original. Fueron 100 frases; **el juez fue la persona**, a ciegas, sobre los 5 primeros de cada receta en 30 de ellas: 316 sí/no, sin saber quién propuso cada municipio. Script: `mapa/big_concurso.py`; hoja rellenada en `docs/concurso-examen-completo.csv`.

| Receta | Acierto en sus 5 primeros (persona, a ciegas) | Frente a luna (hoy) | Coste por 100 frases |
|---|---|---|---|
| **R6 · gpt-6-sol**, razonando poco | **87,3 %** [80-94] | +5,9 (IC de −1 a +13) | 1,14 $ |
| **R1 · gpt-6-luna tal cual (el profesor que usamos)** | **81,4 %** [73-89] | — | 0,05 $ |
| R2 · luna ×3 con candidatos barajados | 79,9 % | −1,5 | 0,17 $ |
| R8 · cascada (baratos + sol en dudas) | 77,3 % | −4,1 | (derivada) |
| R4 · voto de baratos (R2 + R3) | 74,7 % | −6,8 | (derivada) |
| R3 · gpt-5.6-luna | 73,0 % | −8,4 (IC de −17 a −1) | 0,11 $ |
| R7 · Claude Sonnet 5, sin razonar | 66,7 % | −14,8 (IC de −26 a −5) | 1,54 $ |
| R5 · Claude Haiku 4.5 | 62,7 % | −18,8 (IC de −28 a −10) | 0,68 $ |

- **El profesor barato que usamos ya era casi el mejor.** gpt-6-sol saca 6 puntos más, pero la diferencia no llega a ser segura con 30 frases, y cuesta 20 veces más.
- **Los trucos para mejorar al barato no funcionan:** preguntar 3 veces barajando, votar entre baratos o la cascada quedan igual o peor que luna sola. Mezclar con un modelo peor (gpt-5.6-luna) empeora.
- **Claude, sin razonar, queda claramente por debajo** en esta tarea: Sonnet −15 y Haiku −19. Con razonamiento podría ser otra cosa, pero Sonnet costaba el triple.
- **Coste del concurso:** 3,64 $. Sonnet falló en 9 frases, ninguna de la hoja, porque se acabó el saldo de OpenRouter.
- **Lectura:** el techo lo pone el profesor, pero el barato bien elegido está cerca del techo. Reetiquetar todo con gpt-6-sol costaría ~35 $ con lotes, para ~+6 puntos de profesor; en el alumno serían unos +4, porque el reranker recupera ~70 % de lo que sabe el profesor.
- **Decisión (28-09):** no se reetiqueta ni se amplía el experimento. El mapa se queda con las etiquetas de `gpt-6-luna`, el reranker afinado y la búsqueda mixta de palabras y significado.
