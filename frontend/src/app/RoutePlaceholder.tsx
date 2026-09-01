import styles from "./App.module.css";

type RoutePlaceholderProps = {
  as?: "main" | "section";
  description: string;
  title: string;
};

export function RoutePlaceholder({ as = "section", description, title }: RoutePlaceholderProps) {
  const Component = as;

  return (
    <Component aria-label={`${title}加载状态`} className={styles.routePlaceholder}>
      <p className={styles.brandTop}>加载中</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </Component>
  );
}
