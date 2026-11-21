"""Query aliases for vocabulary used in the catalog's rankable passages."""

# Each row lists canonical catalog terms, followed by their query-side aliases.
# For intent phrases, keep the context that distinguishes senses such as a purchase
# cancellation, a missing email, and a price in another currency.
QUERY_ALIASES = (
    # Contact and support
    (
        "contacto soporte",
        "contactar|contactarme|comunicarme|comunicar|llamar|llamarlos|teléfono|whatsapp|wasap|wsp",
    ),
    ("escríbenos contacto", "escribir|escribirles|escribo|les escribo|mandar mensaje"),
    ("correo", "email|e-mail|mail"),
    (
        "soporte contacto",
        "atención al cliente|servicio al cliente|atención humana|hablar con alguien|hablar con una persona|hablar con un asesor",
    ),
    ("soporte contacto", "reclamo|reclamar|queja"),
    ("respondemos", "responden|responder|contestan|contestar|contestación|respuesta"),
    (
        "horas hábiles respondemos",
        "tiempo de respuesta|tardan en responder|demoran en contestar|horario de atención|cuándo atienden|atienden",
    ),
    ("centro de ayuda", "mesa de ayuda|servicio técnico"),
    ("soporte ayuda", "archivo dañado|archivo corrupto|no abre|falla de descarga"),
    # Purchase, billing and currency
    (
        "compra pago",
        "comprar|comprarlo|comprarla|compro|compran|adquirir|adquirirlo|adquiero|conpra",
    ),
    (
        "pago página segura",
        "checkout|carrito|pantalla de pago|botón de compra|enlace de compra|link de pago|clic para comprar|click para comprar|clic en comprar",
    ),
    ("pago", "pagar|pagarlo|pagué|paga|pagamos|abonar|aboné"),
    ("página pago", "cómo comprar|cómo se compra|para comprarlo|para comprarla|dónde compro"),
    ("cobro cargo", "cobran|cobrar|cobraron|cobrará|débito bancario"),
    ("medios de pago", "forma de pago|método de pago|opciones de pago|cómo se paga"),
    ("tarjeta", "tarjeta de débito|tarjeta bancaria|datos bancarios"),
    ("transferencia bancaria", "depósito bancario"),
    ("precio", "cuesta|costar|costará|costo|valor"),
    ("moneda", "divisa|pesos|euros|moneda nacional"),
    ("dólares usd", "dólar estadounidense|dólar americano"),
    ("convierte conversión", "convertir|conversiones|tipo de cambio|tasa de cambio"),
    ("impuestos total final", "precio final|importe total|monto total"),
    ("afiliado comisión", "afiliación|enlace de afiliado"),
    # Refunds and withdrawal
    (
        "reembolso",
        "devolución|devoluciones|devolver el dinero|devuelven el dinero|reintegro|reembolsar|rembolso|reenbolso",
    ),
    (
        "reembolso dinero",
        "devolver la plata|recuperar el dinero|recuperar la plata|devolución del dinero|plata de vuelta|me devuelven|me devuelvan|devuelvan la plata|devuelvan el dinero",
    ),
    (
        "revocar arrepentimiento reembolso",
        "cancelar la compra|anular la compra|desistir|desistimiento|revocación|me arrepentí de la compra|me arrepentí de comprar",
    ),
    ("transacción", "número de operación|identificador de la compra|código de compra"),
    # Delivery and access
    ("acceso", "acceder|accedo|ingresar|entrar|descargar|descarga|bajar el archivo"),
    ("correo acceso", "correo de confirmación|recibir el acceso|recibo el acceso"),
    (
        "spam promociones",
        "correo no deseado|bandeja de spam|no me llegó el correo|no recibí el correo|no recibí el mail|no tengo el correo|bandeja de entrada|no recibí el email|no tengo el mail",
    ),
    (
        "archivos disponibles",
        "vigencia del acceso|perder el acceso|acceso permanente|acceso vence|vence el acceso|caduca el acceso",
    ),
    (
        "cambiar correo",
        "correo equivocado|otro email|correo incorrecto|corregir el correo|equivoqué de correo",
    ),
    (
        "confirma pago aprueba",
        "confirmación del pago|confirmación de compra|página de confirmación|página de agradecimiento|página de gracias|pago aprobado|pagado",
    ),
    ("entrega digital", "entrega electrónica|envío digital"),
    ("producto físico", "envío postal|envío a domicilio|en papel|copia física"),
    # Materials, age and practice
    (
        "incluye recibes",
        "incluye|incluido|incluyen|incluido en la compra|contenido del kit|qué trae|qué viene",
    ),
    ("bonos", "bono adicional|extras|material adicional"),
    ("hoja página", "ficha imprimible|fichas de trabajo"),
    ("kit", "paquete de materiales|conjunto de materiales"),
    ("imprimir impresión", "imprimo|impreso|impresa|imprimible|impresora|fotocopiar"),
    ("papelería centro de impresión", "copistería|fotocopiadora"),
    ("pdf digital", "formato electrónico|archivo pdf"),
    ("tarjetas recortables", "tarjetitas|recortar|tarjetas para recortar"),
    ("plastificar", "laminar|enmicado"),
    ("pósteres", "afiche|cartel|lámina"),
    ("practicar práctica", "practico|ejercitar|ejercicios|practiquen"),
    ("comenzar", "inicio|iniciar|empezar|empiezo|arrancar"),
    ("minutos", "min|minuto"),
    ("guía", "instrucciones de uso|guía de inicio|orientaciones"),
    ("rutina calendario", "cronograma|plan diario"),
    (
        "docentes",
        "maestra|maestro|profe|profesora|profesor|educador|educadora|aula|salón de clases|pedagogía",
    ),
    ("edad", "rango etario|años de edad|franja de edad"),
    ("hijo", "hija"),
    ("niño", "nene|nena|peque|chiquito|chiquita"),
    ("reconocer letras", "identificar letras|reconocimiento de letras"),
    ("sonidos", "pronunciación|pronunciar|fonético|fonética"),
    ("trazos trazar", "repasar con lápiz|delinear|calcar"),
    ("une sílabas", "juntar sílabas|combinar sílabas|unir sílabas"),
    ("juegos", "actividad lúdica|jugar"),
    ("memoria", "memorama|memotest"),
    ("objetos cotidianos", "cosas de casa|objetos del hogar"),
    ("nombre iniciales", "primera letra del nombre|letras del nombre"),
    ("alimentación complementaria", "introducción de alimentos|primeros alimentos"),
    ("bebé", "lactante|bebito|bebita"),
)
