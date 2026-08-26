import Spinner from "../shared/Spinner";

export default function PageLoading() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <Spinner size={32} />
    </div>
  );
}
