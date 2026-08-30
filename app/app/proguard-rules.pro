# kotlinx.serialization keeps generated serializers off the shrink list.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.nseanalysis.app.data.** {
    *** Companion;
}
-keepclasseswithmembers class com.nseanalysis.app.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}
