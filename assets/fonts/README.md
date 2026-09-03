# Fonts

The interface targets **Space Grotesk** (display) and **DM Mono** (data). Neither
is bundled here, because both are OFL-licensed and redistributing them is your
call to make, not this repo's default.

Drop the `.ttf` or `.otf` files into this folder and they are registered
automatically at startup. Nothing else needs changing.

    Space Grotesk  https://fonts.google.com/specimen/Space+Grotesk
    DM Mono        https://fonts.google.com/specimen/DM+Mono

Without them the app falls back, in order, to Inter / Segoe UI / SF Pro for
display and JetBrains Mono / Cascadia / SF Mono / Consolas for mono. The layout
is metric-tolerant, so the fallbacks look intentional rather than broken.
