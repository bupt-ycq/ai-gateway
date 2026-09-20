package router

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func TestDemoPaymentRoutesRequireOptInAndAuthentication(t *testing.T) {
	gin.SetMode(gin.TestMode)
	engine := gin.New()
	registerDemoPaymentRoutes(engine.Group("/api/user"))
	for _, enabled := range []string{"", "false", "true"} {
		t.Run("enabled="+enabled, func(t *testing.T) {
			t.Setenv("PAYMENT_DEMO_ENABLED", enabled)
			for _, route := range []struct {
				method string
				path   string
			}{
				{http.MethodGet, "/api/user/demo-payment/status"},
				{http.MethodPost, "/api/user/demo-payment/orders"},
				{http.MethodPost, "/api/user/demo-payment/orders/demo_missing/resolve"},
			} {
				response := httptest.NewRecorder()
				engine.ServeHTTP(response, httptest.NewRequest(route.method, route.path, nil))
				if enabled == "true" {
					assert.Equal(t, http.StatusUnauthorized, response.Code)
				} else {
					assert.Equal(t, http.StatusNotFound, response.Code)
				}
			}
		})
	}
}
