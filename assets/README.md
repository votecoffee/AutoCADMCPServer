# Application icon

`autocad.ico` bundles the supplied PNG images at 16, 20, 24, 32, 48, 64, 128 and 256 pixels. Each embedded PNG is retained byte for byte; no resizing or artwork changes are applied. `autocad.png` is the original 256-pixel image used in the project README.

Windows setup assigns the ICO to the checkout-local `AutoCAD MCP Server.lnk` shortcut. The generated shortcut contains local paths and is ignored by Git and excluded from source packages. Setup recreates it for each checkout.
