import com.android.build.api.variant.LibraryAndroidComponentsExtension

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    if (name == "reactive_ble_mobile") {
        // BLE 5.5 supports this Flutter SDK but still declares compileSdk 33.
        // Flutter's AndroidX embedding needs API 34+; apply after its own DSL.
        plugins.withId("com.android.library") {
            extensions.getByType<LibraryAndroidComponentsExtension>().finalizeDsl {
                it.compileSdk = 36
            }
        }
    }
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
