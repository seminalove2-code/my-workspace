/**
 * 홈페이지 상담 신청을 구글 스프레드시트로 받는 스크립트
 *
 * 설정 방법 (10분)
 * 1. 구글 스프레드시트를 새로 만든다.
 * 2. 메뉴 [확장 프로그램] → [Apps Script] 를 연다.
 * 3. 이 파일 내용을 전부 붙여넣고 저장한다.
 * 4. [배포] → [새 배포] → 유형: 웹 앱
 *    - 실행 사용자: 나
 *    - 액세스 권한: 모든 사용자
 * 5. 배포하면 나오는 "웹 앱 URL"(https://script.google.com/macros/s/.../exec)을 복사한다.
 * 6. site/index.html 의 const ENDPOINT = ''; 따옴표 안에 붙여넣는다.
 * 7. 홈페이지에서 직접 한 번 신청해 보고 시트에 줄이 생기는지 확인한다.
 */

const LABELS = {
  career: { 'new': '처음', '1-3': '1~3년', '4+': '4년 이상' },
  market: { fair: '베이비페어', biz: '사업자', both: '둘 다' },
};

function doPost(e) {
  const p = e.parameter;
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(['신청 일시', '이름', '연락처', '경력', '관심 시장', '개인정보 동의', '신청 페이지']);
  }
  sheet.appendRow([
    new Date(),
    p.name || '',
    "'" + (p.phone || ''),
    LABELS.career[p.career] || p.career || '',
    LABELS.market[p.market] || p.market || '',
    p.agree ? '동의' : '',
    p.page || '',
  ]);
  return ContentService.createTextOutput('ok');
}
