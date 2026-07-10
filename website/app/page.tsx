import NovaApp from "@/components/NovaApp";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const demo = params.demo === "1" || params.demo === "true";
  return <NovaApp demo={demo} />;
}
