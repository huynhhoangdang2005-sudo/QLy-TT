plugins {
    id("com.android.application")
}

android {
    namespace = "vn.tronha.tenant"
    compileSdk = 36

    defaultConfig {
        applicationId = "vn.tronha.tenant"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
    }
}

dependencies {
    implementation("com.google.mlkit:text-recognition:16.0.1")
}
