import { mkdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
const out = new URL("./out/", import.meta.url);
mkdirSync(out, { recursive: true });
const BASE = "http://127.0.0.1:3008";
// Workflow ids live in a shared n8n; a host may keep an earlier prefix.
const PREFIX = process.env.N8N_PREFIX || "fleet";
const sources = ["1c", "yandex-pro", "fines", "telematics"];
const normalizers = {
  "1c": "({vehicle_code:r.Ref_Key,mileage:String(r.Distance),charges:String(r.AccruedAmount)})",
  "yandex-pro": "({vehicle_code:r.car_id,payments:String(r.income)})",
  fines:
    "({vehicle_code:r.registration,fine:String(r.amount),external_id:r.resolution})",
  telematics: "({vehicle_code:r.vehicle,mileage:String(r.odometer)})",
};
for (const source of sources) {
  let num = 0;
  const node = (name, type, pos, parameters, extra = {}) => ({
    id: source + "-" + ++num,
    name,
    type: "n8n-nodes-base." + type,
    typeVersion:
      type === "httpRequest"
        ? 4.2
        : type === "code"
          ? 2
          : type === "webhook"
            ? 2
            : type === "scheduleTrigger"
              ? 1.2
              : 1,
    position: pos,
    parameters,
    ...extra,
  });
  const http = (name, pos, url, parameters = {}, extra = {}) =>
    node(
      name,
      "httpRequest",
      pos,
      { url, options: { timeout: 20000 }, ...parameters },
      {
        onError: "continueErrorOutput",
        retryOnFail: true,
        maxTries: 2,
        waitBetweenTries: 1000,
        ...extra,
      },
    );
  const nodes = [
    node(
      "Запуск из кабинета",
      "webhook",
      [0, 0],
      {
        httpMethod: "POST",
        path: PREFIX + "-" + source,
        responseMode: "lastNode",
        options: {},
      },
      { webhookId: PREFIX + "-" + source },
    ),
    node("По расписанию", "scheduleTrigger", [0, 200], {
      rule: {
        interval: [{ field: "cronExpression", expression: "7 */1 * * *" }],
      },
    }),
    http(
      "Выбрать активные сессии",
      [220, 200],
      BASE + "/api/mock/schedule/" + source,
      {
        authentication: "genericCredentialType",
        genericAuthType: "httpHeaderAuth",
      },
      {
        credentials: {
          httpHeaderAuth: {
            id: PREFIX + "-schedule-" + source,
            name: "Парк · расписание " + source,
          },
        },
      },
    ),
    node("Контекст запуска", "code", [440, 0], {
      jsCode:
        "const data=$input.first().json; const runs=data.runs||[data.body||data]; return runs.map(c=>{if(!c.run||!c.space||!c.signature)throw new Error('Нет подписанного контекста');return {json:c}});",
    }),
    http(
      "Загрузить источник",
      [660, 0],
      BASE + "/api/mock/" + source + "/snapshot",
      {
        method: "POST",
        sendBody: true,
        specifyBody: "json",
        jsonBody: "={{$json}}",
      },
    ),
    node(
      "Нормализовать данные",
      "code",
      [880, 0],
      {
        mode: "runOnceForEachItem",
        jsCode: `const raw=$json;if(raw.mode!=='synthetic'||!Array.isArray(raw.value))throw new Error('Неверная схема источника');const rows=raw.value.map(r=>${normalizers[source]});for(const r of rows){if(!r.vehicle_code)throw new Error('Нет автомобиля');for(const [k,v] of Object.entries(r)){if(!['vehicle_code','external_id'].includes(k)&&(!Number.isFinite(Number(v))||Number(v)<0))throw new Error('Некорректное значение');}}return {json:{context:raw.context,rows,signature:raw.signature,execution_id:String($execution.id)}};`,
      },
      { onError: "continueErrorOutput" },
    ),
    http(
      "Подписанный пакет → учёт",
      [1100, 0],
      BASE + "/api/v1/integrations/ingest",
      {
        method: "POST",
        sendBody: true,
        specifyBody: "json",
        jsonBody: "={{$json}}",
      },
    ),
    node("Ошибка источника", "code", [880, 240], {
      jsCode:
        "throw new Error('Источник не прошёл проверку или приём. Учётные операции не изменены.');",
    }),
  ];
  const connections = {};
  const link = (a, b, error) =>
    (connections[a] = {
      main: [
        [{ node: b, type: "main", index: 0 }],
        ...(error ? [[{ node: error, type: "main", index: 0 }]] : []),
      ],
    });
  link("Запуск из кабинета", "Контекст запуска");
  link("По расписанию", "Выбрать активные сессии");
  link("Выбрать активные сессии", "Контекст запуска", "Ошибка источника");
  link("Контекст запуска", "Загрузить источник");
  link("Загрузить источник", "Нормализовать данные", "Ошибка источника");
  link("Нормализовать данные", "Подписанный пакет → учёт", "Ошибка источника");
  link("Подписанный пакет → учёт", "Готово", "Ошибка источника");
  nodes.push(
    node("Готово", "code", [1320, 0], { jsCode: "return $input.all();" }),
  );
  const w = {
    id: PREFIX + "-" + source,
    name: "Парк · " + source,
    active: false,
    nodes,
    connections,
    settings: {
      executionOrder: "v1",
      saveDataSuccessExecution: "all",
      saveDataErrorExecution: "all",
      executionTimeout: 60,
    },
    versionId: createHash("sha256")
      .update(JSON.stringify(nodes))
      .digest("hex")
      .slice(0, 32),
    pinData: {},
    tags: [],
  };
  writeFileSync(
    new URL(source + ".json", out),
    JSON.stringify(w, null, 2),
  );
}
console.log("Generated four credential-free workflow definitions");
