# Laya contra jev: el alumno gratuito que aprendió del profesor de pago

Fecha: 24 de septiembre de 2026. Estado del experimento.

## 1. La pregunta

Laya (Convai Innovations, Apache 2.0) salió tres días después de jev con la misma idea y casi la misma API: un modelo de "Sistema 1" que contesta preguntas tipadas (Noul, Choice, Score) en una sola pasada. Es gratis, corre en local y es unas 5 veces más rápido. ¿Puede sustituir a jev?

Respuesta corta: **sin entrenar, no; entrenado con las decisiones de jev, sí, al menos en el comecocos.** El alumno acabó empatando con el profesor en 20 partidas iguales, gratis y a 60 ms por decisión. Pero hizo falta entender por qué perdía, y la respuesta no era "imitar mejor".

## 2. Qué es Laya

| | Laya | jev |
|---|---|---|
| Licencia | Apache 2.0, pesos descargables | API cerrada |
| Tamaño | 421 M (inglés, ModernBERT-large) o 322 M (multilingüe, mmBERT-base) | no publicado |
| Contexto | 1.024 tokens (el multilingüe llega a 8.192) | 32k por estado y pregunta, 64k por petición |
| Opciones por pregunta | se hunde por encima de ~20 (Banking77: 0,43 frente a 0,87) | hasta 255 |
| Latencia medida por nosotros | ~60 ms (RTX 2070) | ~300 ms |
| Coste | 0 $ | 0,042 $ por millón de tokens |

Entrenamiento según su ficha: por refuerzo con reglas de puntuación propias (RLCD), sobre 13 familias de tareas de texto (enrutado de intenciones, moderación, tema, tono, correos, relevancia de búsqueda...). No publican los conjuntos de datos concretos. La versión afinada `typed-decisions` se entrenó con `LocalLLaMA/typed-decisions`: 6.000 decisiones sintéticas de cuatro flujos de empresa. Su propia ficha lo resume: *"a fast base to specialise, not a zero-shot decision engine"*.

## 3. Montaje: destilar jev en Laya

- **Datos:** los logs del comecocos guardan cada estado y las probabilidades que dio jev. Cada línea es un ejemplo de entrenamiento.
- **Objetivo del alumno:** las probabilidades de jev, no solo su opción. Así hereda también su seguridad.
- **Compresión:** jev recibe unos 1.043 tokens por casilla y Laya lee 1.024. Se reescribió el estado en frases cortas: **139 tokens de mediana**.
- **Hardware:** RTX 2070 de 8 GB. Se entrenan las 4 capas de arriba y la cabeza de decisión (75 M parámetros); el resto se congela en media precisión.
- **Examen:** 9 partidas que el alumno no ve nunca, siempre las mismas en todas las versiones.

## 4. Resultados, versión a versión

| | Datos de entrenamiento | Tiempo | Coincide con jev en cruces | En cruces con rival cerca | Dar la vuelta (de 30) |
|---|---|---|---|---|---|
| Laya sin entrenar | — | — | 48 % | — | 0 |
| Regla "huir del rival" (código) | — | — | 76 % | 85 % | — |
| v1: números sueltos | 5.340 | 19 min | 62 % | — | 0 |
| v2: comparaciones en palabras | 5.340 | 20 min | 80 % | — | 0 |
| v3: +6 partidas, delante/detrás en palabras | 10.049 | 37 min | 86,6 % | 92,4 % | 6 |
| v4: +20 partidas de jev, +10 DAgger, peso al peligro | 29.779 | 67 min | **92,3 %** | **97 %** | **15** |

En partida:

| | Semillas | Ganadas | Puntos de media | Vidas perdidas |
|---|---|---|---|---|
| jev | 1001-1006 | 5 de 6 | 4.450 | 12 |
| Laya v2 | 1001-1006 | 0 de 6 | 3.553 | 18 |
| Laya v3 | 1001-1006 | 0 de 6 | 4.105 | 18 |
| jev | 2001-2020 | 7 de 20 | — | — |
| Laya v3 (con jev corrigiendo en la sombra) | 4001-4010 | 3 de 10 | — | — |
| **jev** | **5001-5020** | **6 de 20** | **3.438** | **52** |
| **Laya v4** | **5001-5020** | **5 de 20** | **3.507** | **54** |

## 5. El cara a cara final (mismas 20 semillas, que ninguno vio al entrenar)

| | jev (profesor) | Laya v4 (alumno) |
|---|---|---|
| Partidas ganadas | 6 de 20 | 5 de 20 |
| Puntos de media | 3.438 | 3.507 |
| Mejor partida | 5.720 | 5.920 |
| Tiempo por decisión | ~300 ms | ~60 ms |
| Coste | ~0,035 $ por partida | 0 $ |

Empate técnico. Dato curioso: **ninguna semilla la ganan los dos**. Con la misma semilla el juego empieza igual, pero en cuanto una decisión difiere la partida es otra.

## 6. Lecciones

1. **Laya sin entrenar decide al azar** (48 % en cruces de 2-3 salidas). No es un defecto oculto: su ficha lo dice.
2. **Lo que más ayudó no fue el modelo, sino el texto.** Un codificador de texto compara mal números repartidos entre opciones. Cuando el código escribe la comparación en palabras ("más sitio", "rival más cerca"), el acuerdo sube del 62 % al 80 % con los mismos datos.
3. **Parte de jev es explicable.** Una regla de tres pasos (más sitio para huir, bolita más cercana, más bolitas) reproduce el 86 % de sus decisiones en cruces. jev la encontró sin que nadie se la escribiera.
4. **Imitar mejor no es jugar mejor.** De la v2 a la v4 el acuerdo subió del 80 % al 92 % y las victorias no se movieron de forma medible.
5. **Seis partidas engañan.** El 5 de 6 de jev contra el 0 de 6 de Laya se convirtió en 6 de 20 contra 5 de 20 con más partidas. Para comparar hacen falta 20 o más partidas con las mismas semillas.
6. **El alumno se mete en sitios que el profesor nunca pisó.** Laya moría acorralada, con todas las salidas a 0-1 casillas de sitio, y jev casi nunca llega ahí, así que no había ejemplos de eso. Solución clásica (DAgger): Laya juega, jev contesta en la sombra a cada estado al que llega Laya, y se reentrena con esas correcciones.
7. **Los listones se miden, no se copian.** La escala de probabilidades del alumno no es la del profesor. La confianza mínima pasó de 0,25 (jev) a 0,018-0,061 según la versión, calibrada para caer en la regla de seguridad tan a menudo como jev.

## 7. El mapa con Laya sin entrenar

"Luces de España" pregunta a jev un Choice de 255 lugares. Laya no aguanta tantas opciones, así que se montó un embudo en una sola pasada: 20 zonas (Andalucía y Castilla y León partidas por provincias) y una pregunta por zona. La probabilidad de cada lugar es P(zona) x P(lugar | zona). Se midió con 30 frases, con jev como referencia (coste: 0,02 $).

| | Mismo lugar que jev | Lugar de jev en su top 10 |
|---|---|---|
| Laya sin entrenar (mejor variante) | 10 % | 20 % |
| Buscador de palabras de 30 líneas, sin IA | 33 % | 73 % |

- El modelo en inglés no sirve con frases en castellano (probabilidades planas); hay que usar el multilingüe.
- Laya elige Baleares o Deià para 9 de las 30 frases. Cuando no sabe, cae en su opción de siempre.
- Con la zona correcta dada, acierta el lugar de jev el 37 % de las veces (al azar, el 8 %), y muchos fallos son razonables: Zarautz para el surf, León para la catedral gótica.
- **Conclusión:** la información está en los datos (San Sebastián dice "pintxos"), pero Laya no se entrenó para emparejar un deseo con descripciones de lugares. Sin entrenar, un buscador tonto le gana.

## 8. Costes y tiempos del experimento completo

- **jev:** unos 1,79 $ en total. 46 partidas completas, 6.982 correcciones DAgger y 30 frases del mapa.
- **Laya:** 0 $ por decisión. Entrenar las cuatro versiones llevó unas 2 horas y 5 minutos de GPU en una RTX 2070.
- **Un tropiezo de memoria:** con 8 capas en fp32 el entrenamiento desbordaba la gráfica (6-10 s por paso). Con 4 capas y lo congelado en fp16 quedó en 0,4 s por paso. Un entrenamiento se perdió porque el sistema se quedó sin RAM.

## 9. Cautelas

- Cada partida con jev usa `JEV_PROVIDER` vía OpenRouter; el `$` que imprime `play.mjs` es el acumulado del servidor, no el de cada partida.
- Las semillas 1001-1006 entraron en el entrenamiento de v3 y v4 (partidas de jev). La comparación limpia es la de 5001-5020.
- Todo es un solo juego y un solo laberinto. No hay ninguna garantía de que la receta generalice a otra tarea sin volver a medir.

## 10. Cómo reproducirlo

```
# datos y entrenamiento (entorno aparte con PyTorch CUDA y laya 0.3.20)
python pacman/distill/dataset.py
.venv-laya/Scripts/python pacman/distill/train.py --epochs 2
.venv-laya/Scripts/python pacman/distill/train.py --eval-only models/laya-pacman-v4

# jugar
python pacman/server.py                                          # jev, puerto 8770
LAYA_STUDENT=models/laya-pacman-v4 .venv-laya/Scripts/python pacman/server.py --brain laya --port 8771
.venv-laya/Scripts/python pacman/server.py --brain laya --shadow --port 8771   # DAgger
node pacman/tests/play.mjs --host 127.0.0.1:8771 --seed 5008

# mapa
.venv-laya/Scripts/python mapa/tests/laya_vs_jev.py
```

Ficheros: `pacman/distill/` (compact.py, dataset.py, train.py, laya_client.py), resultados en `pacman/distill/data/` (report-v1..v4.json, final/), modelos en `models/laya-pacman-v1..v4`, mapa en `mapa/laya_map.py` y `mapa/tests/`.
