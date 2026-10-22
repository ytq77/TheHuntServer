FROM ubuntu:resolute-20260927 AS build
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git cmake ninja-build build-essential \
    qt6-base-dev qt6-httpserver-dev qt6-websockets-dev libqt6sql6-sqlite \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY .build/vendor-source/ /vendor-source/
RUN cd /vendor-source && sha256sum -c SHA256SUMS \
    && tar -xzf shadnet.tar.gz --strip-components=1 -C /src \
    && mkdir -p /src/externals/protobuf /src/externals/abseil-cpp \
    && tar -xzf protobuf.tar.gz --strip-components=1 -C /src/externals/protobuf \
    && tar -xzf abseil.tar.gz --strip-components=1 -C /src/externals/abseil-cpp
COPY fixes/stun_server.cpp fixes/stun_server.h /src/src/
RUN printf '\nadd_subdirectory(clientsample)\n' >> CMakeLists.txt \
    && cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
       -DFETCHCONTENT_SOURCE_DIR_ABSL=/src/externals/abseil-cpp \
       -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DABSL_PROPAGATE_CXX_STD=ON \
    && cmake --build build --target shadnet shadnet-sample test_bloodborne_summon_broker --parallel 2 \
    && ctest --test-dir build --output-on-failure

# Same Ubuntu/Qt package family as the builder; no private/local base image.
# Qt development packages intentionally retain their complete runtime dependency
# closure. This favors a reproducible first deployment over minimum image size.
FROM ubuntu:resolute-20260927
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl qt6-base-dev qt6-httpserver-dev qt6-websockets-dev \
    libqt6sql6-sqlite \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 shadnet \
    && useradd --uid 10001 --gid 10001 --no-create-home shadnet
LABEL org.opencontainers.image.source="https://github.com/ytq77/TheHuntServer" \
      org.opencontainers.image.revision="shadnet-5a849a192fd4450593c57b10697316ac324c856e" \
      org.opencontainers.image.licenses="GPL-2.0-or-later" \
      local.bloodborne.stun-framing="legacy4-and-ps4-6"
COPY --from=build /src/build/shadnet /usr/local/lib/shadnet/shadnet
COPY --from=build /src/build/worlds.cfg /usr/local/lib/shadnet/worlds.cfg
COPY --from=build /src/build/scoreboards.cfg /usr/local/lib/shadnet/scoreboards.cfg
COPY --from=build /src/build/clientsample/shadnet-sample /usr/local/bin/shadnet-sample
COPY --from=build /vendor-source/ /usr/local/share/shadnet/source/
COPY fixes/ /usr/local/share/shadnet/fixes/
COPY --chmod=755 entrypoint.sh /usr/local/bin/shadnet-entrypoint
USER 10001:10001
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/shadnet-entrypoint"]
