import type { StoreServiceClient } from "../../bindings/store/v1/StoreServiceClientPb";
import type { ApplicationViewData } from "../../bindings/ubo/v1/ubo_pb";

export interface ApplicationPageProps {
  data: ApplicationViewData.AsObject;
  store: StoreServiceClient;
}
