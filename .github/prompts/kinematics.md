Actúa como experto en cinemática CNC y responde en español. Para una cabeza B+C, convierte un vector normal de herramienta en ángulos B y C. Incluye la derivación matemática, una implementación Python y tests ejecutables con `pytest`.

## Convención cinemática

- El vector de entrada indica la dirección deseada del eje de herramienta +Z, expresada en coordenadas de máquina.
- La orientación se modela como `R = Rz(C) @ Ry(B)`, aplicada al vector base `ez = (0, 0, 1)`; por tanto `n = (sin(B) cos(C), sin(B) sin(C), cos(B))`.
- Los ángulos se expresan en grados en la interfaz pública. Documenta claramente esta convención y advierte que otras máquinas pueden usar signos, ejes u orden de rotación distintos.

## Requisitos

1. Deriva las ecuaciones inversas a partir de la matriz de rotación. Normaliza el vector de entrada; rechaza vectores de longitud cero o no finitos.
2. Usa `B = acos(clamp(nz, -1, 1))` y `C = atan2(ny, nx)`, convirtiendo el resultado a grados. Define el rango principal de B como `[0, 180]` y normaliza C a `[-180, 180)`.
3. Trata la singularidad cuando `|sin(B)|` sea menor que una tolerancia: C no es determinable para una normal paralela al eje Z. Permite un `c_previo` opcional para conservar C; si no se proporciona, usa C=0. Explica que una normal vertical invertida sigue siendo singular.
4. Incluye una comprobación directa que reconstruya la normal desde B y C para validar la solución, comparando vectores normalizados con tolerancia numérica.
5. Implementa una función autocontenida, tipada y documentada, con validación de entradas y excepciones claras. No añadas dependencias externas.
6. Añade tests para casos generales en los cuatro cuadrantes, normal vertical positiva y negativa, vector que requiere normalización, vector inválido y reconstrucción de la normal. Comprueba también el uso de `c_previo` en la singularidad.

Presenta primero la convención y derivación, luego el código Python y finalmente los tests. Mantén explícito que la solución depende de la convención indicada y no presupone límites físicos de los ejes de una máquina concreta.
