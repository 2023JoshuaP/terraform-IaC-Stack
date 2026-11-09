FROM eclipse-temurin:25-jdk AS build
WORKDIR /app
COPY . .
# La construcción y las pruebas se ejecutan dentro del Job de EKS, no localmente.
RUN chmod +x gradlew && ./gradlew --no-daemon --max-workers=2 \
    -Dorg.gradle.jvmargs=-Xmx1024m test bootJar

FROM eclipse-temurin:25-jre
WORKDIR /app
COPY --from=build /app/build/libs/ProceedHub-0.0.1-SNAPSHOT.jar app.jar
USER 10001:10001
EXPOSE 8086
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
