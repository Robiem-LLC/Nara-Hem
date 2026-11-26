# R8 rules for release builds. The libraries below find code by name at run time, which R8 can't
# see, so their classes keep their names and members.

# JNA loads libsodium and maps its functions onto these interfaces by reflection.
-keep class com.sun.jna.** { *; }
-keep class * implements com.sun.jna.** { *; }
-keepclassmembers class * extends com.sun.jna.** { *; }
-dontwarn java.awt.**
-dontwarn com.sun.jna.**

# Lazysodium's native bindings are JNA interfaces.
-keep class com.goterl.lazysodium.** { *; }
-dontwarn com.goterl.lazysodium.**

# Keep line numbers so crash reports (decoded with mapping.txt) point at the right line.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile
