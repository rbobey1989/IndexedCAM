# Integración con el banco CAM de FreeCAD (#11)

Estrategia para añadir 3+2 sobre el banco CAM **sin modificar** FreeCAD ni CAM. Solo se usan APIs públicas de Python.

## Hechos verificados (FreeCAD 1.1.4)

Marcados como *probado* (ejecutado en el AppImage) o *código* (leído en `Mod/CAM/Path`).

| Hecho | Origen |
| --- | --- |
| Un Job admite varios clones rotados (`Model.addObject`) y operaciones con Base en cada uno; el bruto es único y hay que fijar alturas por operación. | probado |
| Las operaciones de área (Adaptive, 3D Surface, Waterline) leen **siempre** `Job.Model` y `Job.Stock`: `SurfaceSupport._identifyFacesAndVoids` solo reconoce las caras de objetos que estén en `Job.Model.Group` (si el objeto no está, `mdlIdx = None` y el op falla o cae al modelo completo), y `Area.areaOpShapeForDepths` devuelve `job.Stock.Shape`. | código |
| Consecuencia medida: con el clon de la orientación **dentro** de `Job.Model`, un `3D Surface` sobre una cara a 45° da 1398 puntos con Z = 0 constante sobre la cara y la cubre (23,3×34,9 de 28,3×40). Con el clon fuera del Job (grupo aparte) el mismo op sale desplazado y con Z positiva. | probado |
| Con los clones en `Job.Model`, `StockFromBase` calcularía el bruto sobre **todas** las copias giradas (62×42×32 → 102×62×62 con dos orientaciones). `Core/job_stock.py` lo evita: sustituye el proxy del bruto por `OrientationStock`, el mismo bruto de CAM pero dejando fuera del `BoundBox` los clones de las orientaciones. El bruto del documento se queda en el tamaño de la pieza, sigue a la pieza si se edita y los 2.5D recuperan su `OpStartDepth` de siempre. | probado |
| Las operaciones CAM generan trayectorias 3 ejes en el marco del Job (plano de trabajo = XY, herramienta = +Z). No existe plano de trabajo inclinado. | código |
| Si el modelo de un Job se coloca con la rotación inversa del marco del Setup, `MillFace` sobre la cara inclinada genera Z constante (probado: cara con normal +X → `G1 … Z60`). | probado |
| `Path.Command` admite `B` y `C` (`G0 B90.000000 C0.000000 X1.000000`). | probado |
| `Job.Fixtures` (G54…) repite **todas** las operaciones por cada fixture (`_buildPostList`); no sirve para asignar operaciones distintas a cada Setup. | código |
| `PostProcessorFactory` busca `<nombre>_post.py` en las rutas de post y en `sys.path`, y usa la clase `<Nombre>` (`postname.title()`). El directorio del addon ya está en `sys.path`, así que `indexedcam_post.py` en la raíz es descubrible. | probado + código |
| Las operaciones se crean por API: `Path.Op.<Tipo>.Create(nombre, parentJob=job)` y se asignan caras con `op.Base = [(objeto, ['FaceN'])]`. | probado |
| Cada operación expone `op.Path.Commands` tras `recompute()`; el `Job` expone `Operations.Group` y `ToolController`. | probado |

## Decisión: el Job lo crea el usuario en CAM; IndexedCAM añade orientaciones dentro de él

El usuario crea el Job y sus operaciones con el banco CAM nativo. IndexedCAM no crea Jobs ni operaciones: añade al Job un grupo de orientaciones y orienta las operaciones que el usuario elija. Con varios Jobs en el documento, las orientaciones pertenecen al Job relacionado con la selección (o al que se elija en un diálogo).

```
Job CAM del usuario  (uno solo, el que creó el usuario)
├─ Operations : todas las operaciones, sin mover ninguna fuera del Job
│    OpA → Base = cara del clon de "Cara A", propiedad IndexedSetup = "Cara A"
│    OpB → Base = cara del clon de "Cara B"
├─ Model      : clon de la pieza + un clon local por Setup (Placement = marco
│               del Setup⁻¹, Shape transitorio, oculto)
├─ Stock      : el del usuario; su proxy (`OrientationStock`) ignora los clones
├─ SetupSheet
├─ Tools
└─ (propiedades ocultas del Job: IndexedCAMSetups, IndexedCAMProgram,
    IndexedCAMSafety, IndexedCAMPOST)
```

Verificado en FreeCAD 1.1.4 (dos clones en un mismo Job con `job.Model.addObject(clone)`; una `MillFace` por clon):

- Cada operación genera la trayectoria en el marco local de su clon (OpB: Z=60 constante sobre la cara inclinada).
- **Problema:** el bruto del Job es único y abarca la unión de los clones. Con los valores por defecto, OpA arranca en Z=61 hasta 30 (384 comandos) en lugar de cortar solo la cara.
- **Solución verificada:** IndexedCAM enlaza por operación `StartDepth`, `SafeHeight` y `ClearanceHeight` al punto más alto de su clon mediante **expresiones** (`<clon>.Shape.BoundBox.ZMax * 1 mm + offset`). `FinalDepth` lo sigue calculando CAM desde la cara. Con expresiones las alturas se actualizan solas al editar el modelo original (con valores fijos quedaban obsoletas y CAM emitía avisos "shape is not planar").

Reglas derivadas:

- Toda operación debe llevar `Base` explícito (cara del clon de su Setup); una operación sin Base usaría todos los clones superpuestos.
- Al reabrir un `.FCStd` FreeCAD vuelve a mostrar los modelos locales; `Gui/restore_observer.py` (instalado en `InitGui.py`) los mantiene ocultos durante la restauración. Al renombrar un Setup, su clon se localiza por `SetupName` y solo cambia de nombre y etiqueta.
- Los modelos locales viven **dentro de `Job.Model`** y no en un grupo aparte: las operaciones de área de CAM solo encuentran las caras de `Base` si el objeto pertenece al modelo del Job (fila de hechos, arriba).
- El bruto del Job es el del usuario y **no crece**: al añadir la primera orientación, `CamBridge.attach_setup` cambia el proxy del bruto existente por `OrientationStock` (`Core/job_stock.py`), que recalcula la misma caja de CAM (mismos `Ext*`, mismo `Placement`) dejando fuera del `BoundBox` los objetos con `LocalPlacement`. El objeto `Stock` del documento no cambia de nombre, etiqueta ni tamaño, y sigue a la pieza si se edita. Los brutos que no derivan del modelo (caja, cilindro…) no se tocan porque no dependen de `Job.Model`.
- CAM dibuja toda trayectoria en el marco del Job (herramienta +Z), lejos de la pieza y del bruto. Al asociar una operación se fija su `Placement` a la inversa del marco local del Setup: la trayectoria se ve sobre la cara que mecaniza y con la herramienta apuntando según B/C. `Path.Commands` sigue en el marco local (lo que usan el programa, la previsualización y el post). Los post nativos que aplican `getPathWithPlacement` verían coordenadas de pieza; el post de IndexedCAM (#19) usará `Path.Commands`.
- Una operación sin `Base` mecanizaría todo el modelo; al asociarla se le asigna la cara con la que se creó la orientación.
- El marco del Setup está en coordenadas de documento, así que `LocalModel` conserva el `Placement` de su fuente (el clon del Job suele estar desplazado); antes la cara quedaba en Z=-1 en lugar de Z=0.
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
- La relación operación → Setup se guarda en `IndexedSetup.operations`, en la propiedad `IndexedSetup` de la operación y en el programa.
- El orden de salida lo define el programa de IndexedCAM, no `Job.Fixtures` ni `OrderOutputBy`.
- Un Job por Setup: se probó y se descartó. Funciona para las operaciones de área, pero duplica Jobs, herramientas y hojas de configuración y saca las operaciones del Job del usuario; con los clones dentro de `Job.Model` el 3D Surface también funciona en un solo Job (ver hechos), que es lo que se usa. También se descartan varios `Fixtures` (repiten todas las operaciones) y parchear operaciones CAM.
- Verificado: `Adaptive` y `Pocket` funcionan sobre el clon local; al editar el modelo original el clon se actualiza solo; 4 clones de una pieza de 150 caras recalculan en ~1 s. Los dressups (Boundary, Tags…) no se han probado todavía.

### Hallazgos de la implementación (#12, #13)

- La `Base` de una operación nativa apunta al clon propio del Job (`Model-<pieza>`), no a la pieza original; los nombres de cara (`FaceN`) coinciden, así que al asociarla se reasigna a las mismas caras del clon local del Setup.
- Una operación o un Setup pueden borrarse en CAM en cualquier momento, por eso `IndexedSetup.operations` y el programa se sincronizan desde el Job (propiedad `IndexedSetup` de cada operación).
- Todo lo de IndexedCAM son propiedades ocultas del propio Job y clones dentro de `Job.Model`: no se añade ningún objeto al documento, así que el árbol queda como el de cualquier Job de CAM.
- La cara del Setup queda en Z=0 local y el centro de la cara en el origen XY del WCS.
- Limitación: se asume un objeto de primer nivel (no dentro de un Body/Part con Placement propio).

## Flujo de usuario

1. En el banco **CAM**: crear el Job con la pieza y sus operaciones (con su herramienta).
2. En **IndexedCAM**: seleccionar una cara → **Face Orientation**. Se calcula B/C, se muestra la triada, se pide el nombre y la orientación se guarda en el Job (propiedad oculta `IndexedCAMSetups`) junto con su clon local en `Job.Model`.
3. En el mismo comando se marcan las operaciones del Job que se realizarán orientadas a ella (opcional; **Assign Operation** lo permite después). Cada operación pasa a la cara equivalente del clon local del Setup y sus alturas se ligan a él.
4. El programa es una lista ordenada de pasos `(Setup, Operación)`; cada paso continúa desde el punto final del anterior y el primero parte de la posición segura inicial.
5. Entre dos pasos de distinto Setup se inserta una **transición** (retirada → giro B/C → aproximación) validada sin colisiones.
6. En todo momento se muestra la **orientación de la herramienta** y los movimientos (ver Visualización).


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
| `Core/cam_bridge.py` | Job existente (`CamBridge(job)`), `attach_setup`, `bind_operation`, `refresh_all`, `detach_setup` | sí |
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

## Estado de la planificación (#16)

`Core/transition_planner.py` implementa los pasos 1–6 anteriores con un `CollisionChecker` inyectable (`collision(punta, B, C) -> Optional[str]`; la implementación con `Part` es #17). Alternativas, por este orden: equivalentes del solver más cercanos primero (C±360°, y (−B, C+180°) si la máquina admite B negativo) y después esfera 1.5× mayor. Muestreo: ≤2° en B/C y 5 mm en tramos lineales. Sin alternativa válida lanza `TransitionError` con la fase, la posición y el obstáculo; nunca devuelve una transición sin validar.

## Comprobador de colisiones (#17)

`PartCollisionChecker(envelope, obstacles, margen=2 mm)` (`Core/collision_checker.py`). Obstáculos en coordenadas de pieza: la pieza y el bruto (*cortables*) y el utillaje. `checker_for_operation(bridge, pieza, operación, envolvente_base, bruto=None, utillaje=())` lo construye con la herramienta real de la operación. El bruto del Job **no** se usa: con un modelo local por Setup su caja abarca todos los clones rotados, no el bruto real; si se necesita, se pasa explícitamente. Dos modos:

- `collision(punta, B, C)`: tránsito; todos los cilindros contra todos los obstáculos.
- `cutting_collision(...)`: mecanizado; solo la parte cortante (`CuttingEdgeHeight`) puede tocar lo cortable. El vástago (resto de la herramienta, con `ShankDiameter`), el portaherramientas y el cabezal no, y el utillaje se comprueba contra todo.

`check_operation(check, op.Path.Commands, frame, B, C)` recorre la trayectoria (puntos cada ≤5 mm; los arcos G2/G3 con I/J se teselan) y devuelve el primer choque con su posición.

**Carrera lineal:** `BCMachine.travel` (`TravelBox`, opcional) limita la posición del pivote de B en coordenadas de pieza (se asume G54 en el origen de la pieza); el planificador rechaza muestras fuera de la caja ("fuera de la carrera lineal").

Verificado con `tests/freecad/check_collision.py` y `check_assign_operation.py`.

## Preview: herramienta por operación y stock tallado

- Cada clip usa la herramienta del `ToolController` de **su** operación (radio, largo y longitud de corte); la lista y el estado del Preview muestran su nombre y dimensiones. La transición usa la herramienta de la operación a la que lleva (no se modela el cambio de herramienta).
- El stock sale de `Job.Stock` y se voxeliza (`Core/voxel_stock.py`, `numpy`): máx. ~800 000 celdas (resolución ≈ 0,5 mm en una pieza de 60×40×30; menor si el bruto es grande). Si el bruto no es una caja, se enmascara con `isInside` con un máximo de 150 000 celdas.
- `Core/stock_timeline.py` talla el stock con el eje real (B/C) y el cilindro de corte de cada operación; las transiciones no cortan. Guarda instantáneas al inicio de cada clip, así que el slider puede ir adelante y atrás. Durante la reproducción la malla se reconstruye unas 6 veces por segundo.
- La vista 3D dibuja la forma real de la herramienta (malla de `ToolBit.Shape`, cacheada por herramienta) de cada operación; si no hay malla se usan cilindros. El portaherramientas y el cabezal siguen siendo cilindros.
- El Preview oculta `Job.Stock` mientras está abierto y lo restaura al cerrar. La casilla «Mostrar stock» lo activa o desactiva.
- Límites: la fresa se modela como cilindro (sin esférica/cónica); la malla es en bloques; los G0 también tallan (si atraviesan material se verá); `Job.Stock` no se actualiza.
