import { HealthStatus } from "@/components/health-status";
import styles from "./page.module.css";

export default function Home() {
  return (
    <main className={styles.main}>
      <section className={styles.card} aria-labelledby="welcome-title">
        <p className={styles.eyebrow}>Group Raiding</p>
        <h1 id="welcome-title">The web app is running</h1>
        <HealthStatus />
      </section>
    </main>
  );
}
