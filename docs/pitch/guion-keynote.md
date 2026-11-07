# Guion del keynote de Prefoundly

Una frase por slide, para decir en voz alta. Lo que está en la pantalla no se lee: se cuenta.
Duración objetivo: 4 minutos más 2 de demo. Demo: https://prefoundly.vercel.app

| # | Slide | Qué decir |
|---|---|---|
| 1 | Portada | "Somos Prefoundly. Hacemos que tu billetera nunca se quede sin plata donde la necesita." |
| 2 | Hacés una transferencia | "Hacés una transferencia desde tu billetera. Llega al instante." |
| 3 | De dónde sale | "Pero la plata no sale de tu billetera. La paga un intermediario, con plata que la billetera le dejó cargada antes." |
| 4 | Prepaga | "Es como una tarjeta prepaga, cargada para todos los usuarios a la vez. Cada transferencia la baja." |
| 5 | Se vacía o sobra | "Si se vacía, pagás una multa. Si sobra, es plata parada que no rinde." |
| 6 | La pregunta | "Entonces la pregunta de todos los días es: ¿cuánto hay que cargar?" |
| 7 | Hoy | "Hoy se carga a ojo: por las dudas, y casi siempre de más." |
| 8 | Prefoundly | "Por eso hicimos Prefoundly: calcula cuánto cargar en tu partner cada día, y lo manda solo." |
| 9 | Agrupa | "Primero agrupa a los usuarios según su comportamiento: los que pagan todo cuando cobran, los que gastan el fin de semana." |
| 10 | Predice | "Después predice cuánto se va a pagar hasta la próxima carga: se esperan 66 millones, y con margen, 117." |
| 11 | Calcula | "Hay 95 millones cargados y hacen falta 117. Carga 21." |
| 12 | La manda solo | "Y la manda solo, a las 9. A las 9:30 ya está acreditada." |
| 13 | Con límites | "Con límites que no puede cambiar: tope por envío, tope por día y cuenta destino fija. Si hace falta más, manda el tope y avisa." |
| 14 | Te explica | "Y te explica cada decisión. Le preguntás en tu idioma, y si querés le das órdenes." |
| 15 | MCP | "Hicimos un servidor MCP: lo conectás a Claude o a tu propio agente para consultarlo, correr la revisión o frenarlo." |
| 16 | Demo | Cambiar a la consola (ver abajo). |
| 17 | Resultado | "Contra la regla fija: 23 % menos plata parada." |
| 18 | Cero | "Y ningún día sin saldo. Ninguna multa." |
| 19 | Un millón | "Con un millón de usuarios, son 55 mil millones de pesos que dejan de estar parados todo el año." |
| 20 | Cierre | "Prefoundly. Cargá lo justo, cuando hace falta." |

## Demo en vivo, en 2 minutos

Antes de subir: abrir https://prefoundly.vercel.app en una ventana de incógnito (así aparece la bienvenida). Tener Claude Code abierto con el MCP conectado.

1. Bienvenida: tocar "Comenzar" y dejar que el recorrido muestre las partes (o saltarlo con Esc si falta tiempo).
2. Monitoreo: "Hoy a las 9 el agente mandó 21 millones al partner, solo. Arriba ven cuánto queda disponible, lo pagado, el desvío contra lo esperado y lo que estima mandar mañana."
3. El gráfico: "Minuto a minuto, lo que se paga de verdad contra lo que esperaba el modelo."
4. El chat: tocar "¿Alcanza el saldo?" o "¿Por qué mandaste ese monto?". Responde Claude con los números del modelo.
5. Historial: "14 días: cuánto repuso, cuánto se pagó y con qué saldo cerró. Cero días con faltante."
6. Conectar agente: "Y todo esto también lo controlás desde tu propio agente, por MCP." Opcional: en Claude Code, "¿cuánto le mandó hoy Prefoundly a cada partner?".

## Si preguntan

- **Los datos son simulados.** Los parámetros de la población, el tipo de cambio y los costos son supuestos. Los feriados son reales, y los bancos argentinos informan de 2 a 5 días hábiles para una transferencia al exterior.
- **Contra qué regla comparamos.** Una regla fija calibrada con las 16 semanas anteriores para no quedarse nunca sin saldo. Ese número de días solo se conoce mirando atrás; Prefoundly decide cada día con el pronóstico.
- **Por qué stablecoin para el finde.** Los bancos no mueven plata de noche ni en fin de semana. Una stablecoin sí, en minutos. Hace falta estar registrado como proveedor de activos virtuales ante la CNV, o usar un partner registrado, y que la cuenta acepte stablecoin.
- **¿Por qué no saca la plata que sobra?** Una vez que la mandás, queda en la fintech: es parte de su negocio. Lo que sobra el viernes baja lo que hay que mandar el lunes.
- **Un millón de usuarios.** Es una proyección desde 20.000. En la simulación en pesos, el capital creció en proporción a los usuarios desde 5.000.
