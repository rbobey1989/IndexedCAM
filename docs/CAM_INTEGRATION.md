# Integración con el banco CAM de FreeCAD (#11)

Estrategia para añadir 3+2 sobre el banco CAM **sin modificar** FreeCAD ni CAM. Solo se usan APIs públicas de Python.

## Hechos verificados (FreeCAD 1.1.4)

Marcados como *probado* (ejecutado en el AppImage) o *código* (leído en `Mod/CAM/Path`).

| Hecho | Origen |
| --- | --- |
| Un Job admite varios clones rotados (`Model.addObject`) y operaciones con Base en cada uno; el bruto es único y hay que fijar alturas por operación. | probado |
| Las operaciones CAM generan trayectorias 3 ejes en el marco del Job (plano de trabajo = XY, herramienta = +Z). No existe plano de trabajo inclinado. | código |
| Si el modelo de un Job se coloca con la rotación inversa del marco del Setup, `MillFace` sobre la cara inclinada genera Z constante (probado: cara con normal +X → `G1 … Z60`). | probado |
| `Path.Command` admite `B` y `C` (`G0 B90.000000 C0.000000 X1.000000`). | probado |
| `Job.Fixtures` (G54…) repite **todas** las operaciones por cada fixture (`_buildPostList`); no sirve para asignar operaciones distintas a cada Setup. | código |
| `PostProcessorFactory` busca `<nombre>_post.py` en las rutas de post y en `sys.path`, y usa la clase `<Nombre>` (`postname.title()`). El directorio del addon ya está en `sys.path`, así que `indexedcam_post.py` en la raíz es descubrible. | probado + código |
| Las operaciones se crean por API: `Path.Op.<Tipo>.Create(nombre, parentJob=job)` y se asignan caras con `op.Base = [(objeto, ['FaceN'])]`. | probado |
| Cada operación expone `op.Path.Commands` tras `recompute()`; el `Job` expone `Operations.Group` y `ToolController`. | probado |

## Decisión: un único Job CAM con un clon local por Setup

Un solo Job reúne todas las operaciones; cada operación se enlaza a un Setup de IndexedCAM.

```
Job CAM único "IndexedCAM_Job"
├─ Modelo (Job.Model): clon local por Setup (Placement = marco del Setup⁻¹)
│    LocalA (Setup "Cara A")   LocalB (Setup "Cara B")   …
└─ Operaciones CAM estándar (UI nativa), cada una con Base = cara de SU clon
     OpA → Setup "Cara A"      OpB → Setup "Cara B"
```

Verificado en FreeCAD 1.1.4 (dos clones en un mismo Job con `job.Model.addObject(clone)`; una `MillFace` por clon):

- Cada operación genera la trayectoria en el marco local de su clon (OpB: Z=60 constante sobre la cara inclinada).
- **Problema:** el bruto del Job es único y abarca la unión de los clones. Con los valores por defecto, OpA arranca en Z=61 hasta 30 (384 comandos) en lugar de cortar solo la cara.
- **Solución verificada:** IndexedCAM enlaza por operación `StartDepth`, `SafeHeight` y `ClearanceHeight` al punto más alto de su clon mediante **expresiones** (`<clon>.Shape.BoundBox.ZMax * 1 mm + offset`). `FinalDepth` lo sigue calculando CAM desde la cara. Con expresiones las alturas se actualizan solas al editar el modelo original (con valores fijos quedaban obsoletas y CAM emitía avisos "shape is not planar").

Reglas derivadas:

- Toda operación debe llevar `Base` explícito (cara del clon de su Setup); una operación sin Base usaría todos los clones superpuestos.
- Los clones se ocultan en la vista; el modelo original sigue siendo el visible.

### Clones ligeros (`LocalModel`)

Un clon por Setup no debe pesar ni en memoria, ni en el archivo, ni en la recomputación. Medido en FreeCAD 1.1.4 con una pieza de 144 taladros y 4 clones:

| Variante | Tamaño `.FCStd` |
| --- | --- |
| Sin clones | 24 KB |
| Clones con `Shape` guardado (copia o compartido) | 105 KB (cada clon guarda su BREP) |
| **`LocalModel` con `Shape` transitorio** (2 clones, pieza simple) | 31 KB |

Diseño adoptado:

- `LocalModel` es un `Part::FeaturePython` con un proxy del addon y propiedades `Source` (enlace al modelo) y `Normal`/Setup.
- La transformación Placement es la inversa del marco local del Setup (`Core/local_placement.py`, matemática pura y testeada): `p_local = Rᵀ (p − origen)`, no la rotación de arco mínimo, para coincidir con la triada y con el post.
- `execute`: `shape = Source.Shape.copy(False)` (**comparte la geometría**, no la duplica), `obj.Shape = shape` y `obj.Placement = rotación del Setup` (hay que fijar el `Placement` del objeto; poner la rotación en el `Shape` no basta).
- `Shape` se marca `Transient`: **no se guarda en el archivo**. Al cargar, `onDocumentRestored` reconstruye la forma directamente (un `touch()` no basta: el clon quedaba con forma nula).
- Memoria: una única geometría compartida por todos los clones; solo cambia la ubicación.
- Los clones dependen de `Source`, así que siguen los cambios paramétricos del modelo sin sincronización manual (resuelve el riesgo abierto de sincronización).
- Verificado: dos clones en un Job, una `MillFace` por clon con alturas propias → OpA (cara +X) Z=60, OpB (cara +Y) Z=40; guardar, reabrir y recalcular restaura clones y trayectorias.

Descartado: `App::Link` como modelo (el Job lo acepta pero crea su propio clon interno, sin ahorro) y clones con `Shape` persistente (archivo proporcional al número de Setups).

Optimización futura si fuese necesario: modo "solo caras" (clon con únicamente la cara del Setup) para operaciones 2.5D en piezas muy pesadas; las operaciones 3D requieren el modelo completo.
- La relación operación → Setup se guarda en `IndexedSetup.operations` (y la inversa en el programa), sin tocar propiedades del Job.
- El orden de salida lo define el programa de IndexedCAM, no `Job.Fixtures` ni `OrderOutputBy`.
- Alternativa descartada: un Job por Setup (multiplica Jobs, herramientas y hojas de configuración). También se descartan varios `Fixtures` (repiten todas las operaciones) y parchear operaciones CAM.
- Verificado: `Adaptive` y `Pocket` funcionan sobre el clon local; al editar el modelo original el clon se actualiza solo; 4 clones de una pieza de 150 caras recalculan en ~1 s. Los dressups (Boundary, Tags…) no se han probado todavía.

## Flujo de usuario

1. Seleccionar una cara → **Face Orientation** (ya implementado): B/C, triada y Setup.
2. Tras guardar el Setup, **elegir una operación CAM** para él (Face, Pocket…). IndexedCAM usa el Job único (lo crea si no existe), añade el clon del Setup si falta, crea la operación con la cara del clon como base, fija sus alturas y abre su panel nativo.
3. La operación **se encadena a la anterior** del programa: el programa es una lista ordenada de pasos `(Setup, Operación)`. Cada paso continúa desde el punto final del anterior; el primero parte de la posición segura inicial.
4. Entre dos pasos de distinto Setup se inserta una **transición** (retirada → giro B/C → aproximación) validada sin colisiones.
5. En todo momento se muestra la **orientación de la herramienta** y los movimientos (ver Visualización).

`IndexedSetup.operations` ya guarda los nombres de operación; la secuencia global vive en el documento junto a los setups (`DocumentStorage`).

## Transiciones sin colisión

Entradas: pose final del paso anterior `(B₁,C₁, punta P₁)`, pose inicial del siguiente `(B₂,C₂, P₂)`, geometría de obstáculos (modelo, material en bruto, utillaje) y envolvente de la herramienta.

Algoritmo (puro, testeable sin FreeCAD salvo el comprobador):

1. **Retirada** del paso anterior a lo largo de su eje de herramienta hasta fuera de la esfera de seguridad.
2. **Esfera de seguridad**: centro = centro del bruto, radio = semidiagonal del bruto + longitud de herramienta/portaherramientas + margen. Con la punta sobre la esfera y la herramienta apuntando radialmente hacia fuera, la herramienta no puede entrar en la pieza.
3. **Giro**: interpolar B/C (paso ≤ 2°) y mover la punta sobre la esfera: `P(t) = c + n(B(t),C(t))·R`. Respetar los límites de `BCMachine`.
4. **Aproximación** radial hasta el punto de entrada de la siguiente operación.
5. **Comprobación**: en cada muestra se construye la envolvente (herramienta + portaherramientas + cabezal) y se comprueba la distancia mínima a cada obstáculo (`Shape.distToShape`) ≥ margen; también los límites de carrera de los ejes lineales.
6. Si falla, probar en orden: alternativas del solver (C+180 con −B, equivalentes ±360), sentido de giro contrario de C, esfera mayor. Si ninguna es válida, **error explícito** con la muestra y el obstáculo; nunca se emite una transición sin validar.

La verificación de colisiones dentro de una operación (cabezal inclinado frente a paredes) reutiliza el mismo comprobador sobre los puntos de `op.Path`.

## Visualización

- `ToolView` (Coin3D, como `TriadView`): modelo simplificado de herramienta + portaherramientas + cabezal con la pose actual (B/C), y la polilínea de la trayectoria transformada a global. Nodos temporales, no se guardan en el documento.
- Se actualiza al seleccionar Setup, operación o transición; en transición, un **reproductor** (deslizador + play) recorre las muestras y colorea en rojo las que colisionan.
- Los datos de máquina (pivote de B, longitud/radio del cabezal) se añaden a la definición de máquina; son necesarios para la envolvente y el TCP.

## Postprocesado

`indexedcam_post.py` (clase `Indexedcam`) recorre el programa y, por paso: emite posicionamiento B/C tras la retirada, selecciona el WCS y las coordenadas de las operaciones. Dos modos, configurables por máquina:

- **Local** (controladores con inclinación de plano: G68.2/G254, CYCLE800, PLANE): se emiten XYZ locales.
- **Máquina** (TCP/G43.4): el post transforma XYZ locales → máquina con la cinemática de `bc_head`.

Modo inicial recomendado: *Máquina*, por ser matemática pura y testeable. Los signos y ceros reales dependen del controlador (ya anotado en `MACHINE.md`).

## Módulos propuestos

| Módulo | Responsabilidad | Depende de FreeCAD |
| --- | --- | --- |
| `Core/program.py` | Secuencia ordenada de pasos y punto final de cada uno | no |
| `Core/local_placement.py` | Transformación parte → marco local y alturas por operación | no |
| `Core/local_model.py` | Clon ligero `LocalModel` por Setup | sí |
| `Core/cam_bridge.py` | Job único, `attach_setup`, `bind_operation`, `refresh_all`, `detach_setup` | sí |
| `Core/transition_planner.py` | Retirada, giro sobre esfera, aproximación, alternativas | no |
| `Core/collision_checker.py` | Interfaz + implementación con `Part` | sí (implementación) |
| `Machine/envelope.py` | Herramienta, portaherramientas, cabezal, pivote | no |
| `Gui/tool_view.py` | Visualización y reproductor | sí |
| `Commands/assign_operation.py` | Comando "Asignar operación" | sí |
| `Post/indexedcam_post.py` | Postprocesador | no (usa `Path`) |

## Riesgos abiertos

- Rendimiento de recomputación con modelos muy pesados (mitigación: modo "solo caras").
- Forma real de herramienta/portaherramientas: las toolbits de CAM pueden traer `Shape`; si no, se usa cilindro/cono simplificado.
- Signos, ceros y pivote reales por máquina.
- Operaciones 3D (Surface/Waterline) con cabezal inclinado exigen comprobación de colisión dentro de la operación.
