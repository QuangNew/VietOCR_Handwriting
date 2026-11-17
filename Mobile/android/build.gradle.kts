import com.android.build.api.variant.LibraryAndroidComponentsExtension

// Use cached SDK/artifacts when building on a metered connection.
if (System.getenv("VIETOCR_OFFLINE_BUILD") == "1") {
    gradle.startParameter.isOffline = true
}

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
    // Flutter plugins sometimes declare their own older/newer build toolchain.
    // Use the same AGP/Kotlin as settings.gradle.kts instead of downloading a
    // second toolchain for app_links/url_launcher on a metered connection.
    buildscript.configurations.configureEach {
        resolutionStrategy.eachDependency {
            if (requested.group == "com.android.tools.build" && requested.name == "gradle") {
                useVersion("8.13.2")
            }
            if (requested.group == "org.jetbrains.kotlin" && requested.name == "kotlin-gradle-plugin") {
                useVersion("2.2.20")
            }
        }
    }
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
