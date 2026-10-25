<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

type Card = {
  deal: { id: string; title: string; stage: string; funnel: string };
  driver?: { name: string; phone: string | null };
  candidate?: { name: string; experience: string | null };
  contract?: { code: string; status: string; start: string; end: string; rate: string; direction: string };
  car?: { code: string; model: string; plate: string; status: string; image?: string };
  money?: { charged: string; paid: string; debt: string; crm_paid: string };
  fines?: { number: string; amount: string }[];
  documents?: { code: string; kind: string; status: string }[];
  note?: string;
  verdict: { ok: boolean; reasons: string[]; kind: string };
};

const cfg = window.B24APP;
const card = ref<Card | null>(null);
const error = ref("");
const busy = ref(false);
const done = ref("");

const rub = (v?: string | null) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(Number(v || 0)) + " ₽";
const gap = computed(() =>
  card.value?.money ? Number(card.value.money.crm_paid || 0) - Number(card.value.money.paid || 0) : 0,
);

async function load() {
  error.value = "";
  try {
    const r = await fetch(`${cfg.api}?action=deal&deal=${cfg.deal}&key=${encodeURIComponent(cfg.key)}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "Учёт не ответил");
    card.value = data;
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function task() {
  busy.value = true;
  try {
    const r = await fetch(`${cfg.api}?action=task&deal=${cfg.deal}&key=${encodeURIComponent(cfg.key)}`, {
      method: "POST",
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error);
    done.value = `Задача №${data.task} поставлена менеджеру`;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <main class="w">
    <header>
      <small>Приложение «Таксопарк» · сделка #{{ cfg.deal }}</small>
      <button class="ghost" @click="load">Обновить</button>
    </header>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-else-if="!card" class="muted">Загружаем данные учёта…</p>

    <template v-else>
      <section :class="['verdict', card.verdict.ok ? 'ok' : 'bad']">
        <b>{{ card.verdict.ok ? "Можно работать" : "Есть замечания" }}</b>
        <ul>
          <li v-for="r in card.verdict.reasons" :key="r">{{ r }}</li>
        </ul>
      </section>

      <section v-if="card.candidate" class="grid">
        <div>
          <small>Кандидат</small><b>{{ card.candidate.name }}</b>
        </div>
        <div>
          <small>Стаж</small><b>{{ card.candidate.experience || "—" }} лет</b>
        </div>
      </section>

      <p v-if="card.note" class="muted">{{ card.note }}</p>

      <template v-if="card.contract && card.car && card.money">
        <section class="grid">
          <div>
            <small>Водитель</small><b>{{ card.driver?.name }}</b
            ><span>{{ card.driver?.phone }}</span>
          </div>
          <div>
            <small>Договор</small><b>{{ card.contract.code }}</b
            ><span>{{ card.contract.start }} — {{ card.contract.end }}</span>
          </div>
          <div class="car">
            <img v-if="card.car.image" :src="card.car.image" alt="" />
            <span
              ><small>Машина</small><b>{{ card.car.model }}</b
              ><span>{{ card.car.plate }} · {{ card.car.code }}</span></span
            >
          </div>
        </section>
        <section class="grid money">
          <div>
            <small>Начислено</small><b>{{ rub(card.money.charged) }}</b>
          </div>
          <div>
            <small>Пришло в учёт</small><b>{{ rub(card.money.paid) }}</b>
          </div>
          <div :class="{ bad: Number(card.money.debt) > 0 }">
            <small>Долг</small><b>{{ rub(card.money.debt) }}</b>
          </div>
          <div :class="{ bad: gap > 0 }">
            <small>«Оплачено» в CRM</small><b>{{ rub(card.money.crm_paid) }}</b>
            <span v-if="gap > 0">больше учёта на {{ rub(String(gap)) }}</span>
          </div>
        </section>
        <section v-if="card.fines?.length">
          <small>Штрафы по машине</small>
          <ul>
            <li v-for="f in card.fines" :key="f.number">№ {{ f.number }} · {{ rub(f.amount) }}</li>
          </ul>
        </section>
        <section v-if="card.documents?.length">
          <small>Документы по машине</small>
          <ul>
            <li v-for="d in card.documents" :key="d.code">{{ d.code }} · {{ d.kind }} · {{ d.status }}</li>
          </ul>
        </section>
      </template>

      <footer>
        <button :disabled="busy" @click="task">Поставить задачу менеджеру</button>
        <span v-if="done" class="okmsg">{{ done }}</span>
      </footer>
    </template>
  </main>
</template>
