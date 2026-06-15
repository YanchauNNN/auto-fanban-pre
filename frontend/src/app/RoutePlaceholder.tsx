import styles from "./App.module.css";

export function RoutePlaceholder({ description, title }: { description: string; title: string }) {
  return (
    <main className={styles.routePlaceholder}>
      <p className={styles.brandTop}>Loading</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </main>
  );
}
