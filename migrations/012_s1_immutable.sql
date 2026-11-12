-- Owner-only upgrade. Do not grant ownership or trigger/function DDL to runtime.
-- This function is owned by the migration/table owner, never by the web role.
CREATE OR REPLACE FUNCTION clinic_merge_drug(from_id integer, to_id integer, actor integer, reason text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE source public.drugs%ROWTYPE; target public.drugs%ROWTYPE;
BEGIN
  IF from_id=to_id OR reason IS NULL OR length(trim(reason))<8 OR length(reason)>500 THEN
    RAISE EXCEPTION 'Chọn hai thuốc khác nhau và lý do gộp hợp lệ' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM public.users u JOIN public.user_roles r ON r.user_id=u.id
                WHERE u.id=actor AND u.active=1 AND r.role='admin') THEN
    RAISE EXCEPTION 'Người gộp phải là quản trị đang hoạt động' USING ERRCODE='42501';
  END IF;
  -- Acquire rows in a stable order, including direct EXECUTE callers.
  PERFORM id FROM public.drugs WHERE id IN (from_id,to_id) ORDER BY id FOR UPDATE;
  SELECT * INTO source FROM public.drugs WHERE id=from_id;
  SELECT * INTO target FROM public.drugs WHERE id=to_id;
  IF source.id IS NULL OR target.id IS NULL OR source.merged_into IS NOT NULL
     OR target.merged_into IS NOT NULL OR target.review_status='inactive' THEN
    RAISE EXCEPTION 'Chọn hai mục đang dùng khác nhau' USING ERRCODE='23514';
  END IF;
  -- Never reuse a caller-created relation. TEMP context has owner-only ACLs,
  -- lives solely inside this call, and disappears on error/transaction rollback.
  IF to_regclass('pg_temp.s1_merge_context') IS NOT NULL THEN
    RAISE EXCEPTION 'Ngữ cảnh gộp không hợp lệ' USING ERRCODE='42501';
  END IF;
  CREATE TEMP TABLE s1_merge_context(source_id integer, target_id integer) ON COMMIT DROP;
  REVOKE ALL ON pg_temp.s1_merge_context FROM PUBLIC;
  INSERT INTO pg_temp.s1_merge_context VALUES(from_id,to_id);
  UPDATE public.drugs SET toxic=CASE WHEN source.toxic<>0 OR target.toxic<>0 THEN 1 ELSE 0 END,
    controlled_type=CASE WHEN COALESCE(target.controlled_type,'')<>'' THEN target.controlled_type ELSE source.controlled_type END
    WHERE id=to_id;
  UPDATE public.clinical_prescription_items SET drug_id=to_id WHERE drug_id=from_id;
  UPDATE public.drugs SET review_status='inactive',merged_into=to_id WHERE id=from_id;
  INSERT INTO public.audit_log(user_id,event,object_type,object_id,details,created_at)
    VALUES(actor,'drug_merged','drug',from_id,
           json_build_object('keep_id',to_id,'reason',regexp_replace(reason,'\m([0-9]{6,}|[A-Za-z]{1,3}[0-9]{5,})\M','[đã che chuỗi định danh]','g'))::text,
           to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00');
  DROP TABLE pg_temp.s1_merge_context;
END $$;
REVOKE ALL ON FUNCTION clinic_merge_drug(integer,integer,integer,text) FROM PUBLIC;

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
DECLARE frozen boolean; owner_name name; context_owner oid;
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
    IF NEW.drug_id IS DISTINCT FROM OLD.drug_id THEN
      SELECT pg_get_userbyid(relowner) INTO owner_name FROM pg_class WHERE oid=TG_RELID;
      IF current_user <> owner_name OR to_regclass('pg_temp.s1_merge_context') IS NULL THEN
        RAISE EXCEPTION 'Chỉ hàm gộp của owner được đổi thuốc đã khóa' USING ERRCODE='23514';
      END IF;
      SELECT relowner INTO context_owner FROM pg_class
        WHERE oid=to_regclass('pg_temp.s1_merge_context') AND relkind='r';
      IF context_owner IS DISTINCT FROM (SELECT relowner FROM pg_class WHERE oid=TG_RELID) THEN
        RAISE EXCEPTION 'Ngữ cảnh gộp không thuộc owner' USING ERRCODE='23514';
      END IF;
      IF NOT EXISTS(SELECT 1 FROM pg_temp.s1_merge_context
                    WHERE source_id=OLD.drug_id AND target_id=NEW.drug_id) THEN
        RAISE EXCEPTION 'Cặp thuốc không khớp tham số hàm gộp' USING ERRCODE='23514';
      END IF;
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
