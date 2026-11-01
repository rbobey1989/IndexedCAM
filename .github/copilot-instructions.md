# IndexedCAM — instrucciones para Copilot

## Objetivo y límites
- Proyecto de Workbench externo para FreeCAD que añade mecanizado indexado 3+2.
- No modificar FreeCAD ni el núcleo del banco CAM; toda funcionalidad debe residir en este Workbench.
- Mantener los cambios modulares y directamente relacionados con IndexedCAM.

## Requisitos de implementación
- Usar Python, las API de FreeCAD, PySide y Coin3D disponibles en el entorno del proyecto.
- Añadir anotaciones de tipo a funciones, métodos y atributos cuando sea viable; documentar módulos, clases y API pública.
- Separar responsabilidades (por ejemplo, selección/geometría, cálculo de orientación, cinemática, interfaz y visualización). Evitar acoplar la lógica geométrica a la interfaz.
- Usar las convenciones y versiones de API ya presentes en el repositorio; no asumir que están disponibles módulos o funciones de otras versiones de FreeCAD.
- Validar entradas geométricas y manejar errores de selección o geometría degenerada sin alterar el documento del usuario de forma inesperada.

## Conceptos del dominio
Usar de forma coherente los conceptos Setup, Tool Orientation, Indexed Machining, Work Coordinate System (WCS) y Machine Kinematics. Mantener diferenciados los sistemas de coordenadas de pieza, herramienta y máquina, y documentar las convenciones de ejes y unidades.

## Prioridad de trabajo actual
1. Selección de caras.
2. Obtención y validación de normales de cara.
3. Cálculo de orientaciones de herramienta a partir de las normales.
4. Visualización del sistema local XYZ mediante Coin3D.

Implementar primero estas capacidades; no ampliar el alcance a generación de trayectorias ni a cambios del núcleo CAM salvo que se solicite expresamente.
