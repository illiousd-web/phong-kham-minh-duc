-- Owner-only upgrade. Do not grant ownership or trigger/function DDL to runtime.
CREATE OR REPLACE FUNCTION s1_prescription_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF OLD.snapshot IS NOT NULL OR OLD.status IN ('locked','cancelled') THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Đơn đã khóa không được xóa' USING ERRCODE='23514';
    END IF;
    IF OLD.status <> 'locked' OR NEW.status <> 'cancelled'
       OR length(trim(COALESCE(NEW.cancellation_reason,''))) < 8
       OR NEW.cancelled_at IS NULL OR NEW.version <> OLD.version + 1
       OR (to_jsonb(NEW) - ARRAY['status','version','cancellation_reason','cancelled_at']) IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status','version','cancellation_reason','cancelled_at']) THEN
      RAISE EXCEPTION 'Nội dung đơn đã khóa bất biến; chỉ được hủy có lý do' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION s1_prescription_item_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE frozen boolean;
BEGIN
  IF TG_OP='INSERT' THEN
    SELECT status <> 'draft' OR snapshot IS NOT NULL INTO frozen FROM clinical_prescriptions WHERE id=NEW.prescription_id FOR SHARE;
    IF frozen THEN RAISE EXCEPTION 'Không thêm dòng vào đơn đã khóa' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='UPDATE' AND NEW.prescription_id <> OLD.prescription_id THEN
    RAISE EXCEPTION 'Không chuyển dòng sang đơn khác' USING ERRCODE='23514';
  END IF;
  SELECT status <> 'draft' OR snapshot IS NOT NULL INTO frozen FROM clinical_prescriptions WHERE id=OLD.prescription_id FOR SHARE;
  IF frozen THEN
    -- Drug merges may repoint the catalog FK; printed content stays frozen.
    IF TG_OP='DELETE' THEN
      RAISE EXCEPTION 'Dòng đơn đã khóa không được xóa' USING ERRCODE='23514';
    END IF;
    IF NEW.drug_id IS DISTINCT FROM OLD.drug_id AND
       (OLD.drug_id::text IS DISTINCT FROM current_setting('clinic.merge_from', true) OR
        NEW.drug_id::text IS DISTINCT FROM current_setting('clinic.merge_to', true)) THEN
      RAISE EXCEPTION 'Chỉ được đổi thuốc trong giao dịch gộp hợp lệ' USING ERRCODE='23514';
    END IF;
    IF (to_jsonb(NEW)-'drug_id') IS DISTINCT FROM (to_jsonb(OLD)-'drug_id') THEN
      RAISE EXCEPTION 'Nội dung dòng đơn đã khóa bất biến' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION s1_lab_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF OLD.status='approved' OR OLD.snapshot IS NOT NULL THEN
    RAISE EXCEPTION 'Phiếu đã duyệt bất biến; tạo phiếu điều chỉnh thay thế' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION s1_lab_result_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE frozen boolean;
BEGIN
  IF TG_OP='INSERT' THEN
    SELECT status='approved' OR snapshot IS NOT NULL INTO frozen FROM lab_reports WHERE id=NEW.report_id FOR SHARE;
    IF frozen THEN RAISE EXCEPTION 'Không thêm kết quả vào phiếu đã duyệt' USING ERRCODE='23514'; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP='UPDATE' AND NEW.report_id <> OLD.report_id THEN
    RAISE EXCEPTION 'Không chuyển kết quả sang phiếu khác' USING ERRCODE='23514';
  END IF;
  SELECT status='approved' OR snapshot IS NOT NULL INTO frozen FROM lab_reports WHERE id=OLD.report_id FOR SHARE;
  IF frozen THEN
    RAISE EXCEPTION 'Kết quả đã duyệt bất biến' USING ERRCODE='23514';
  END IF;
  IF TG_OP='DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION s1_outbox_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'Outbox đơn đã khóa không được xóa' USING ERRCODE='23514';
  END IF;
  IF (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') OR
     NEW.status <> 'cancelled' OR OLD.status <> 'pending' OR
     NOT EXISTS(SELECT 1 FROM clinical_prescriptions WHERE id=OLD.prescription_id AND status='cancelled') THEN
    RAISE EXCEPTION 'Nội dung outbox bất biến' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER s1_prescription_immutable BEFORE UPDATE OR DELETE ON clinical_prescriptions FOR EACH ROW EXECUTE FUNCTION s1_prescription_guard();
CREATE TRIGGER s1_prescription_items_immutable BEFORE INSERT OR UPDATE OR DELETE ON clinical_prescription_items FOR EACH ROW EXECUTE FUNCTION s1_prescription_item_guard();
CREATE TRIGGER s1_lab_immutable BEFORE UPDATE OR DELETE ON lab_reports FOR EACH ROW EXECUTE FUNCTION s1_lab_guard();
CREATE TRIGGER s1_lab_results_immutable BEFORE INSERT OR UPDATE OR DELETE ON lab_results FOR EACH ROW EXECUTE FUNCTION s1_lab_result_guard();
CREATE TRIGGER s1_outbox_immutable BEFORE UPDATE OR DELETE ON prescription_outbox FOR EACH ROW EXECUTE FUNCTION s1_outbox_guard();

REVOKE ALL ON FUNCTION s1_prescription_guard(), s1_prescription_item_guard(),
 s1_lab_guard(), s1_lab_result_guard(), s1_outbox_guard() FROM PUBLIC;
