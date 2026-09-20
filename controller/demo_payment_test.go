package controller

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/QuantumNous/new-api/common"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestDemoPaymentRejectsInvalidPayload(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.POST("/orders", CreateDemoPaymentOrder)
	router.POST("/orders/:order_no/resolve", ResolveDemoPaymentOrder)
	for _, test := range []struct {
		name string
		path string
		body string
	}{
		{"fractional cents", "/orders", `{"amount_cents":100.5,"payment_method":"alipay"}`},
		{"overflow", "/orders", `{"amount_cents":9223372036854775808,"payment_method":"alipay"}`},
		{"missing fields", "/orders", `{}`},
		{"invalid method", "/orders", `{"amount_cents":100,"payment_method":"unknown"}`},
		{"trailing object", "/orders", `{"amount_cents":100,"payment_method":"alipay"} {}`},
		{"oversized", "/orders", strings.Repeat(" ", 1025) + `{}`},
		{"bad outcome", "/orders/demo_missing/resolve", `{"outcome":"pending"}`},
		{"missing outcome", "/orders/demo_missing/resolve", `{}`},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := httptest.NewRecorder()
			request := httptest.NewRequest(http.MethodPost, test.path, strings.NewReader(test.body))
			request.Header.Set("Content-Type", "application/json")
			router.ServeHTTP(response, request)
			assert.Equal(t, http.StatusBadRequest, response.Code)
			var body struct {
				Success bool `json:"success"`
			}
			require.NoError(t, common.Unmarshal(response.Body.Bytes(), &body))
			assert.False(t, body.Success)
		})
	}
}
