# Integración con el banco CAM de FreeCAD (#11)

Estrategia para añadir 3+2 sobre el banco CAM **sin modificar** FreeCAD ni CAM. Solo se usan APIs públicas de Python.

## Hechos verificados (FreeCAD 1.1.4)

Marcados como *probado* (ejecutado en el AppImage) o *código* (leído en `Mod/CAM/Path`).

| Hecho | Origen |
| --- | --- |
| Las operaciones CAM generan trayectorias 3 ejes en el marco del Job (plano de trabajo = XY, herramienta = +Z). No existe plano de trabajo inclinado. | código |
| Si el modelo de un Job se coloca con la rotación inversa del marco del Setup, `MillFace` sobre la cara inclinada genera Z constante (probado: cara con normal +X → `G1 … Z60`). | probado |
| `Path.Command` admite `B` y `C` (`G0 B90.000000 C0.000000 X1.000000`). | probado |
| `Job.Fixtures` (G54…) repite **todas** las operaciones por cada fixture (`_buildPostList`); no sirve para asignar operaciones distintas a cada Setup. | código |
| `PostProcessorFactory` busca `<nombre>_post.py` en las rutas de post y en `sys.path`, y usa la clase `<Nombre>` (`postname.title()`). El directorio del addon ya está en `sys.path`, así que `indexedcam_post.py` en la raíz es descubrible. | probado + código |
| Las operaciones se crean por API: `Path.Op.<Tipo>.Create(nombre, parentJob=job)` y se asignan caras con `op.Base = [(objeto, ['FaceN'])]`. | probado |
| Cada operación expone `op.Path.Commands` tras `recompute()`; el `Job` expone `Operations.Group` y `ToolController`. | probado |

## Decisión: un Job CAM por Setup

```
Setup (IndexedCAM)  ──►  Job CAM "IndexedCAM_<setup>"
                          ├─ Modelo: clon con Placement = marco local del Setup⁻¹
                          ├─ Operaciones CAM estándar (UI nativa de CAM)
                          └─ Trayectorias en coordenadas locales (Z = normal de la cara)
```

- La **cara elegida queda horizontal** en el clon: cualquier operación CAM (Face, Pocket, Profile, Adaptive, Drilling…) funciona sin cambios.
- IndexedCAM **orquesta**: crea el Job, enlaza el clon, lista las operaciones y gestiona orden, transiciones y postprocesado. La edición de cada operación se hace con el panel estándar de CAM.
- Alternativas descartadas: un único Job con varios `Fixtures` (repite todas las operaciones) y parchear/subclasear operaciones CAM (viola la restricción de no tocar CAM).
- El clon debe seguir al modelo original (objeto `Part::FeaturePython` que copia `Shape` y fija `Placement`). **Pendiente de verificar** que los cambios paramétricos del original refrescan las operaciones.
- El origen del WCS local es el origen del Setup; la numeración de caras del clon coincide con la del original (misma topología).

## Flujo de usuario

1. Seleccionar una cara → **Face Orientation** (ya implementado): B/C, triada y Setup.
2. Tras guardar el Setup, **elegir una operación CAM** para él (Face, Pocket…). IndexedCAM crea el Job del Setup si no existe, crea la operación con la cara como base y abre su panel nativo.
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
| `Core/cam_bridge.py` | Crear Job por Setup, clon local, crear/listar operaciones, leer `Path` | sí |
| `Core/transition_planner.py` | Retirada, giro sobre esfera, aproximación, alternativas | no |
| `Core/collision_checker.py` | Interfaz + implementación con `Part` | sí (implementación) |
| `Machine/envelope.py` | Herramienta, portaherramientas, cabezal, pivote | no |
| `Gui/tool_view.py` | Visualización y reproductor | sí |
| `Commands/assign_operation.py` | Comando "Asignar operación" | sí |
| `Post/indexedcam_post.py` | Postprocesador | no (usa `Path`) |

## Riesgos abiertos

- Sincronización del clon con el modelo original.
- Forma real de herramienta/portaherramientas: las toolbits de CAM pueden traer `Shape`; si no, se usa cilindro/cono simplificado.
- Signos, ceros y pivote reales por máquina.
- Operaciones 3D (Surface/Waterline) con cabezal inclinado exigen comprobación de colisión dentro de la operación.
