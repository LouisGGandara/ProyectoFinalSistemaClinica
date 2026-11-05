# Sistema de atención y gestión de turnos

Aplicación de escritorio para una clínica. Registra pacientes, genera turnos y los atiende en orden con dos colas, una prioritaria y una normal. Guarda un historial de acciones en el que se puede deshacer la última. Está hecha en Python con Tkinter y guarda los datos en archivos JSON en UTF-8.

Proyecto final de Programación IV, trabajo individual.

## Requisitos

- Python 3.11 o superior. Se probó con 3.11, 3.12, 3.13 y 3.14.
- Tkinter, que viene con el instalador de Python para Windows.
- No usa librerías externas, así que no hay nada que instalar con pip.

## Cómo ejecutar la aplicación

Desde la carpeta del proyecto, en la terminal de PyCharm:

```
python main.py
```

También se puede abrir `main.py` en PyCharm y presionar Run. La aplicación lee y guarda los datos en la carpeta `data/` del proyecto, sin importar desde qué carpeta se inicie. Si falta algún archivo JSON, lo crea vacío; si falta `users.json`, crea los dos usuarios de prueba.

## Usuarios de prueba

| Usuario | Contraseña | Rol | Qué puede hacer |
|---|---|---|---|
| `admin` | `Admin123` | Administrador | Todo: registrar, atender, cancelar turnos, ver y deshacer el historial de acciones, y administrar usuarios |
| `recepcion` | `Recep123` | Recepcionista | Registrar y modificar pacientes, generar, atender y finalizar turnos, buscar, y ver atendidos y estadísticas. No cancela turnos, no deshace acciones y no ve las pestañas Historial de acciones ni Usuarios |

Cada usuario puede cambiar su propia contraseña en Archivo > Cambiar mi contraseña. Si se cambian, `tests/generate_demo_data.py` y `tests/bulk_demo.py` vuelven a dejar estas contraseñas.

## Pruebas automáticas

```
python -m unittest discover tests
```

Son 496 pruebas de la lógica, la persistencia y los scripts de datos. No abren ventanas y trabajan en carpetas temporales, así que no tocan `data/`.

## Demo de consola

```
python tests/console_demo.py
```

Recorre un día corto de la clínica con `ClinicSystem` y muestra el estado después de cada paso: registro, colas, atención, cancelación, deshacer y estadísticas. Trabaja en una carpeta temporal que borra al terminar, así que no cambia `data/`. Sirve de respaldo si la interfaz falla el día de la presentación.

## Datos de demostración

Cierra la aplicación antes de usar estos scripts, porque una ventana abierta volvería a escribir `data/` en su siguiente guardado. Los dos copian primero `data/` a `backups/data-AAAAMMDD-HHMMSS/` y, si algo falla, `data/` queda como estaba.

```
python tests/bulk_demo.py
```

Deja en `data/` los datos de la entrega: una semana de la clínica con 300 pacientes, de los últimos cinco días hábiles hasta la hora en que se corre. Empieza con la clínica vacía, así que correrlo otra vez da otra semana en lugar de sumar pacientes. Durante la semana hay atenciones, turnos nuevos para pacientes que regresan, correcciones de datos, cancelaciones, acciones deshechas y dos turnos de recepción. Al terminar muestra un resumen y abre la aplicación con el mismo sistema; entra como `admin` para ver el historial de acciones de la semana. Ese historial solo vive en memoria, así que se pierde al cerrar la ventana, pero los pacientes, turnos y atenciones quedan en `data/`. Opciones:

- `--sin-ventana`: solo llena `data/` y muestra el resumen.
- `--semilla N`: otros nombres y decisiones (2026 por defecto).

```
python tests/generate_demo_data.py
```

Deja en `data/` un juego pequeño para pruebas rápidas: 10 pacientes, 4 prioritarios con criterios distintos, 3 atendidos, 1 cancelado y 6 en las dos colas. Con `--rapido` corre sin pausas entre pasos.

## Estructura de carpetas

```
ProyectoFinalSistemaClinica/
├── main.py                   punto de entrada: crea la ventana
├── models/                   clases del dominio
│   ├── person.py             Person, clase abstracta
│   ├── user.py               User, Administrator y Receptionist
│   ├── permissions.py        Permission, los permisos de cada rol
│   ├── patient.py            Patient
│   ├── care_type.py          NormalCare y PriorityCare
│   ├── ticket.py             Ticket
│   ├── ticket_status.py      estados de un turno
│   ├── care_record.py        registro de una atención finalizada
│   └── actions.py            acciones del historial y cómo se deshace cada una
├── structures/               estructuras de datos
│   ├── ticket_queue.py       cola de turnos (FIFO)
│   └── stack.py              pila del historial (LIFO)
├── services/                 lógica del sistema
│   ├── clinic_system.py      ClinicSystem, la fachada que usa la interfaz
│   ├── user_manager.py       usuarios e inicio de sesión
│   ├── patient_manager.py    pacientes
│   ├── ticket_manager.py     turnos, colas y atenciones
│   ├── action_history.py     historial de acciones y deshacer
│   ├── search.py             criterios de búsqueda
│   └── stats.py              estadísticas
├── persistence/
│   └── json_repository.py    lectura y escritura de los JSON en UTF-8
├── utils/
│   ├── exceptions.py         excepciones propias
│   ├── validator.py          validaciones de los datos que se escriben
│   └── dates.py              formato de fechas y reloj
├── ui/                       interfaz con Tkinter
│   ├── app.py                ventana, avisos y errores no previstos
│   ├── login_view.py         inicio de sesión
│   ├── main_view.py          ventana principal, menús y pestañas
│   ├── base_tab.py           BaseTab, la pestaña base abstracta
│   ├── widgets.py            tabla, mensajes y piezas de formulario
│   ├── password_dialog.py    diálogo para cambiar contraseña
│   └── *_tab.py              una pestaña por archivo: Registro, Turnos y
│                             colas, Búsqueda, Atendidos, Historial de
│                             acciones, Estadísticas y Usuarios
├── tests/                    pruebas automáticas (test_*.py) y scripts
│   ├── console_demo.py       demo de consola
│   ├── generate_demo_data.py 10 pacientes para pruebas rápidas
│   └── bulk_demo.py          semana simulada de la entrega
├── data/                     datos de la aplicación
│   ├── users.json
│   ├── patients.json
│   ├── tickets.json
│   ├── care_records.json
│   └── ticket_counter.json   siguiente número de turno
└── docs/
    ├── entrega1_analisis/    primera entrega: análisis
    ├── entrega2_diseno/      segunda entrega: diagrama de clases inicial
    └── entrega_final/        diagrama de clases final (classes.puml y uml/),
                              manual de usuario, tablas de pruebas y capturas
```

Git ignora dos cosas que la aplicación o los scripts crean solos: `errors.log`, donde la aplicación anota el detalle de un error no previsto, y `backups/`, con las copias de `data/`.
