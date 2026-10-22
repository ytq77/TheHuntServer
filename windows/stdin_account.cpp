// SPDX-License-Identifier: GPL-2.0-or-later
// The Hunt: read UTF-8 credentials from stdin rather than process arguments.
#define QT_NO_KEYWORDS
#include <QJsonDocument>
#include <QJsonObject>
#include <chrono>
#include <iostream>
#include <thread>
#include "client.h"

int main(int argc, char** argv) {
    if (argc != 4) return 2;
    std::string line;
    std::getline(std::cin, line);
    if (line.size() > 16384) return 2;
    const auto doc = QJsonDocument::fromJson(QByteArray::fromStdString(line));
    if (!doc.isObject()) return 2;
    const auto obj = doc.object();
    auto field = [&](const char* name) { return obj.value(name).toString().toUtf8().toStdString(); };
    shadnetclient::ShadNetClient client;
    bool done = false;
    auto error = shadnetclient::ErrorType::Malformed;
    client.onCreateResult = [&](shadnetclient::ErrorType result) { error = result; done = true; };
    client.onLoginResult = [&](const shadnetclient::LoginResult& result) { error = result.error; done = true; };
    if (client.connect(argv[1], static_cast<uint16_t>(std::stoi(argv[2])))) {
        if (std::string(argv[3]) == "register")
            client.createAccount(field("name"), field("password"), "", field("email"), field("key"));
        else if (std::string(argv[3]) == "login")
            client.login(field("name"), field("password"), "");
        else return 2;
        for (int i = 0; i < 1000 && !done; ++i) {
            client.update();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
    client.disconnect();
    const bool ok = done && error == shadnetclient::ErrorType::NoError;
    std::cout << "{\"ok\":" << (ok ? "true" : "false") << ",\"error\":\""
              << (done ? shadnetclient::errorName(error) : "ConnectionFailed") << "\"}" << std::endl;
    return ok ? 0 : 1;
}
